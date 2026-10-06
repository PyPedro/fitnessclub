import json
import sys
from collections import OrderedDict
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy.exc import IntegrityError
from werkzeug.datastructures import FileStorage

from app import create_app, db
from app.models import ImportacaoEstoque, Produto, ProdutoImagem
from scripts import importar_estoque
from scripts.importar_estoque import criar_produto_sem_cadastro, ler_inventario, planejar_importacao
from app.routes import chave_cor, cor_para_hex, imagem_disponivel, nome_cor, validar_arquivos_imagem, variantes_com_cor_hex


def test_inventario_inicial_tem_referencias_unicas_e_total_esperado():
    inventario = ler_inventario()

    assert len(inventario) == 60
    assert sum(item['referencia'] == '459' for item in inventario) == 1
    assert sum(
        quantidade
        for item in inventario
        for cores in item['estoque'].values()
        for quantidade in cores.values()
    ) == 6704


def test_inventario_soma_cores_repetidas_e_preserva_tamanho_especial():
    inventario = {item['referencia']: item for item in ler_inventario()}

    assert inventario['523']['estoque']['M']['Açaí'] == 8
    assert inventario['461']['estoque']['M']['Caramelo'] == 10
    assert inventario['366']['estoque']['GG2']['Branco'] == 19
    assert inventario['382']['estoque']['G']['Terracota'] == 12


def test_ler_inventario_aceita_zerou_e_quantidade_em_linha_separada(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Conj teste Ref 999\n'
        'M\n'
        'Zerou\n'
        'G\n'
        '9\n'
        'Azul marinho\n'
        '3\n'
        'Preto\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario()

    assert inventario == [{
        'nome': 'Conj teste',
        'referencia': '999',
        'estoque': {'M': OrderedDict(), 'G': {'Azul marinho': 9, 'Preto': 3}},
    }]


def test_ler_inventario_aceita_cabecalhos_e_cores_no_formato_enviado_pelo_usuario(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Top 2 tiras de viés\n'
        'M\n'
        '7 rosé\n'
        '3Azul marinho\n'
        'G\n'
        'Zerou\n'
        'Conj short e top e tiara ref 518\n'
        'M\n'
        '1 caramelo\n'
        'G\n'
        '0\n'
        'Conj short duplo e top Ref ref 410\n'
        'M\n'
        '1 Pink cereja\n'
        '11rosé\n'
        'G\n'
        '2 preto\n'
        '3Azul marinho\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario()
    por_ref = {item['referencia']: item for item in inventario}

    assert '518' in por_ref
    assert por_ref['518']['estoque']['M']['Caramelo'] == 1
    assert por_ref['410']['estoque']['M']['Pink cereja'] == 1
    assert por_ref['410']['estoque']['M']['Rosé'] == 11
    assert por_ref['410']['estoque']['G']['Azul marinho'] == 3
    assert por_ref['410']['estoque']['G']['Preto'] == 2


def test_ler_inventario_cria_referencia_sintetica_para_itens_sem_referencia(monkeypatch, tmp_path):
    arquivo = tmp_path / 'inventario.txt'
    arquivo.write_text(
        'Top 2 tiras de viés\n'
        'M\n'
        '7 rosé\n'
        'G\n'
        '3 Azul marinho\n'
        'Conj short e top e tiara ref 518\n'
        'M\n'
        '1 caramelo\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(importar_estoque, 'INVENTORY_FILE', arquivo)

    inventario = importar_estoque.ler_inventario(gerar_referencia_ausente=True)
    assert {item['referencia'] for item in inventario} == {'0', '518'}
    assert inventario[0]['nome'] == 'Top 2 tiras de viés'
    assert inventario[0]['estoque']['M']['Rosé'] == 7
    assert inventario[0]['estoque']['G']['Azul marinho'] == 3


def test_cores_nomeadas_preservam_cor_de_pedidos_legados():
    assert cor_para_hex('Pink Cereja') == '#c51e62'
    assert nome_cor('#1c1c1a') == 'Preto'
    assert chave_cor('#172b4d') == chave_cor('Azul marinho')
    assert nome_cor('#123456') == 'Personalizada (#123456)'
    variante = variantes_com_cor_hex([{'cor': 'Azul marinho', 'tamanhos': []}])[0]
    assert variante['cor'] == 'Azul marinho'
    assert variante['cor_hex'] == '#172b4d'
    assert variante['cor_nome'] == 'Azul marinho'


def test_produto_legado_completa_tamanhos_padrao_sem_perder_grade_especial():
    produto = Produto(
        codigo='GRADE-LEGADA',
        nome='Produto legado',
        preco=25,
        etiqueta='TESTE',
        imagem_url='',
        grade=json.dumps([{'nome': 'GG2', 'estoque': 3, 'preco': 25}]),
        variantes=json.dumps([{
            'cor': None,
            'tamanhos': [{'nome': 'GG2', 'estoque': 3, 'preco': 25}],
        }]),
    )

    tamanhos_grade = produto.grade_config
    tamanhos_variante = produto.variantes_config[0]['tamanhos']
    nomes_padrao = {'P', 'M', 'G', 'GG', 'XG', 'XGG'}

    assert nomes_padrao.issubset({tamanho['nome'] for tamanho in tamanhos_grade})
    assert nomes_padrao.issubset({tamanho['nome'] for tamanho in tamanhos_variante})
    assert next(tamanho for tamanho in tamanhos_variante if tamanho['nome'] == 'GG2')['estoque'] == 3
    assert all(tamanho['estoque'] == 0 for tamanho in tamanhos_variante if tamanho['nome'] in nomes_padrao)


def test_cria_produto_novo_com_preco_zero_sem_imagem_e_grade_completa():
    inventario = {item['referencia']: item for item in ler_inventario()}
    produto = criar_produto_sem_cadastro(inventario['366'])

    assert produto.codigo == '366'
    assert produto.nome == 'Short duplo plus size'
    assert produto.preco == 0
    assert produto.imagem_url == ''
    assert produto.estoque_gg == 19
    assert {'cor': 'Branco', 'tamanhos': [{'nome': 'GG2', 'estoque': 19, 'preco': 0.0}]} in json.loads(produto.variantes)


def test_catalogo_vazio_planeja_criacao_das_60_referencias():
    correspondencias, problemas = planejar_importacao([], ler_inventario())

    assert len(correspondencias) == 60
    assert not problemas
    assert all(produto is None and metodo == 'novo produto' for _, produto, metodo in correspondencias)


def test_vitrine_omite_imagens_antigas_ausentes_e_serve_banners(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        db.session.add(Produto(
            codigo='473',
            nome='Conj short saia e top',
            preco=0,
            etiqueta='NOVO',
            imagem_url='uploads/arquivo-que-nao-existe.pdf',
            cores=json.dumps(['Azul marinho']),
            variantes=json.dumps([{'cor': 'Azul marinho', 'tamanhos': [{'nome': 'M', 'estoque': 7, 'preco': 0}]}]),
        ))
        produto = Produto.query.filter_by(codigo='473').one()
        db.session.add(ProdutoImagem(produto=produto, imagem_url='uploads/arquivo-que-nao-existe.pdf', ordem=0))
        db.session.commit()

    client = app.test_client()
    resposta = client.get('/')
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert 'Foto não cadastrada' in html
    assert 'src="/static/"' not in html
    assert 'arquivo-que-nao-existe.pdf' not in html
    assets = (
        'banner_hero1.jpeg', 'banner_macaquinho.jpeg', 'banner_lounge.jpeg',
        'cat_conjuntos.jpeg', 'cat_leggings.jpeg', 'cat_casacos.jpeg', 'cat_tops.jpeg',
    )
    assert all(client.get(f'/static/img/{asset}').status_code == 200 for asset in assets)


def test_vitrine_filtra_por_categoria_e_agrupa_por_nome(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()

    with app.app_context():
        db.session.add_all([
            Produto(codigo='001', nome='Conj short e top', preco=99.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='002', nome='Conj short e top', preco=109.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='003', nome='Top 2 tiras de viés', preco=69.9, etiqueta='NOVO', imagem_url=''),
            Produto(codigo='004', nome='Legging com bolso', preco=89.9, etiqueta='NOVO', imagem_url=''),
        ])
        db.session.commit()

    with app.test_client() as client:
        resposta = client.get('/?categoria=conjuntos')
        assert resposta.status_code == 200
        html = resposta.get_data(as_text=True)
        assert 'Conj short e top' in html
        assert 'Top 2 tiras de viés' not in html
        assert 'Legging com bolso' not in html
        assert html.count('class="product-card"') == 1


def test_api_cadastro_rejeita_pdf_sem_criar_produto(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/produtos/cadastrar', data={
            'codigo': 'PDF-404',
            'nome': 'Arquivo inválido',
            'preco': '10',
            'grade': json.dumps([{'nome': 'M', 'estoque': 1, 'preco': 10}]),
            'cores': json.dumps(['Preto']),
            'variantes': json.dumps([{'cor': 'Preto', 'tamanhos': [{'nome': 'M', 'estoque': 1, 'preco': 10}]}]),
            'imagens': (BytesIO(b'%PDF-1.7 arquivo'), 'catalogo.pdf', 'application/pdf'),
        })

    assert resposta.status_code == 400
    assert 'somente imagens' in resposta.get_json()['mensagem']
    with app.app_context():
        assert Produto.query.filter_by(codigo='PDF-404').count() == 0


def test_api_cadastro_e_edicao_aceitam_produto_sem_cor(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    app.config['UPLOAD_FOLDER'] = str(tmp_path)

    imagem = BytesIO()
    Image.new('RGB', (1, 1), color='red').save(imagem, format='PNG')
    imagem.seek(0)
    tamanhos = [{'nome': 'M', 'estoque': 4, 'preco': 25}]
    variante_sem_cor = [{'cor': None, 'tamanhos': tamanhos}]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        cadastro = client.post('/api/admin/produtos/cadastrar', data={
            'codigo': 'SEM-COR-01',
            'nome': 'Produto sem cor',
            'preco': '25',
            'grade': json.dumps(tamanhos),
            'cores': json.dumps([None]),
            'variantes': json.dumps(variante_sem_cor),
            'imagens': (imagem, 'produto.png', 'image/png'),
        })

        with app.app_context():
            produto = Produto.query.filter_by(codigo='SEM-COR-01').one()
            produto_id = produto.id
            tamanhos_cadastrados = json.loads(produto.variantes)[0]['tamanhos']
            assert {tamanho['nome'] for tamanho in tamanhos_cadastrados} == {'P', 'M', 'G', 'GG', 'XG', 'XGG'}
            assert next(tamanho for tamanho in tamanhos_cadastrados if tamanho['nome'] == 'M')['estoque'] == 4
            assert all(tamanho['estoque'] == 0 for tamanho in tamanhos_cadastrados if tamanho['nome'] != 'M')

        edicao = client.post(
            f'/api/admin/produtos/editar/{produto_id}',
            data={
                'grade': json.dumps(tamanhos),
                'cores': json.dumps([None]),
                'variantes': json.dumps(variante_sem_cor),
            },
        )

    assert cadastro.status_code == 200
    assert cadastro.get_json()['sucesso'] is True
    assert edicao.status_code == 200
    assert edicao.get_json()['sucesso'] is True
    with app.app_context():
        produto = db.session.get(Produto, produto_id)
        tamanhos_editados = json.loads(produto.variantes)[0]['tamanhos']
        assert {tamanho['nome'] for tamanho in tamanhos_editados} == {'P', 'M', 'G', 'GG', 'XG', 'XGG'}
        assert next(tamanho for tamanho in tamanhos_editados if tamanho['nome'] == 'M')['estoque'] == 4


def test_api_cadastro_salva_conjunto_tamanhos_e_atualiza_referencia_renomeada(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    app.config['UPLOAD_FOLDER'] = str(tmp_path)
    with app.app_context():
        relacionado = Produto(codigo='TOP-02', nome='Top', preco=50, etiqueta='TESTE', imagem_url='')
        db.session.add(relacionado)
        db.session.commit()
        relacionado_id = relacionado.id

    imagem = BytesIO()
    Image.new('RGB', (1, 1), color='red').save(imagem, format='PNG')
    imagem.seek(0)
    tamanhos = [
        {'nome': nome, 'estoque': 2, 'preco': 100}
        for nome in ('P', 'M', 'G', 'GG', 'XG', 'XGG')
    ]
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/produtos/cadastrar', data={
            'codigo': 'LEGGING-02',
            'nome': 'Legging',
            'preco': '100',
            'grade': json.dumps(tamanhos),
            'cores': json.dumps(['Preto']),
            'variantes': json.dumps([{'cor': 'Preto', 'tamanhos': tamanhos}]),
            'eh_conjunto': 'true',
            'referencia_conjunto': 'TOP-02',
            'imagens': (imagem, 'legging.png', 'image/png'),
        })

        dados_produtos = client.get('/api/admin/produtos').get_json()
        resposta_renomear = client.post(
            f'/api/admin/produtos/editar/{relacionado_id}',
            data={'codigo': 'TOP-03', 'nome': 'Top'},
        )

    assert resposta.status_code == 200
    assert resposta.get_json()['sucesso'] is True
    produto = next(item for item in dados_produtos if item['codigo'] == 'LEGGING-02')
    assert produto['eh_conjunto'] is True
    assert produto['referencia_conjunto'] == 'TOP-02'
    assert [item['nome'] for item in produto['grade']] == ['P', 'M', 'G', 'GG', 'XG', 'XGG']
    assert resposta_renomear.status_code == 200
    with app.app_context():
        assert Produto.query.filter_by(codigo='LEGGING-02').one().referencia_conjunto == 'TOP-03'


def test_apply_cria_60_produtos_e_nao_duplica_na_reexecucao(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)
    monkeypatch.setattr(sys, 'argv', ['scripts.importar_estoque', '--apply'])

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 60
        produto = Produto.query.filter_by(codigo='056').one()
        assert produto.preco == 0
        assert produto.imagem_url == ''
        assert ImportacaoEstoque.query.count() == 1

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 60


def test_importacao_por_arquivo_texto_adiciona_itens_novos(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    arquivo = tmp_path / 'lote-novo.txt'
    arquivo.write_text(
        'Conj teste lote novo Ref 999\n'
        'M\n'
        '2 Azul marinho\n'
        '1 Preto\n'
        'G\n'
        '3 Verde militar\n'
        '1 Rosé\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'arquivo': (arquivo.open('rb'), 'lote-novo.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='999').first()
        assert produto is not None
        assert produto.estoque_m == 3
        assert produto.estoque_g == 4


def test_importacao_por_arquivo_texto_aceita_campo_arquivo_alternativo(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    arquivo = tmp_path / 'lote-alternativo.txt'
    arquivo.write_text(
        'Conj lote alternativo Ref 998\n'
        'M\n'
        '2 Azul marinho\n'
        '1 Preto\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'file': (arquivo.open('rb'), 'lote-alternativo.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='998').first()
        assert produto is not None
        assert produto.estoque_m == 3


def test_importacao_por_arquivo_texto_pode_adicionar_referencia_nova_apos_importacao_inicial(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    with app.app_context():
        db.session.add(ImportacaoEstoque(chave=importar_estoque.IMPORT_KEY))
        db.session.commit()

    arquivo = tmp_path / 'lote-novo-ref-456.txt'
    arquivo.write_text(
        'Conj short saia e top e tiara ref 456\n'
        'M\n'
        '7 rosé\n'
        '3 Azul neblina\n'
        '1 verde militar\n'
        '2 grafite\n'
        'G\n'
        '9 Azul marinho\n',
        encoding='utf-8',
    )

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque', data={
            'arquivo': (arquivo.open('rb'), 'lote-novo-ref-456.txt'),
        })

    assert resposta.status_code == 200
    dados = resposta.get_json()
    assert dados['sucesso'] is True
    assert dados['importada'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='456').first()
        assert produto is not None
        assert produto.nome == 'Conj short saia e top e tiara'
        assert produto.estoque_m == 13
        assert produto.estoque_g == 9


def test_api_importacao_em_lote_reutiliza_logica_de_estoque(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post('/api/admin/importar-estoque')

    assert resposta.status_code in (200, 400)
    dados = resposta.get_json()
    assert 'sucesso' in dados
    assert 'mensagem' in dados


def test_api_impede_referencia_duplicada_no_cadastro_e_na_edicao(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    with app.app_context():
        db.session.add_all([
            Produto(codigo='REF-10', nome='Produto 10', preco=10, etiqueta='TESTE', imagem_url=''),
            Produto(codigo='REF-20', nome='Produto 20', preco=10, etiqueta='TESTE', imagem_url=''),
        ])
        db.session.commit()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        cadastro = client.post('/api/admin/produtos/cadastrar', data={'codigo': ' ref-10 ', 'nome': 'Cópia'})
        edicao = client.post('/api/admin/produtos/editar/2', data={'codigo': 'REF-10', 'nome': 'Produto 20'})

    assert cadastro.status_code == 409
    assert cadastro.get_json()['sucesso'] is False
    assert edicao.status_code == 409
    assert edicao.get_json()['sucesso'] is False


def test_indice_unico_do_banco_bloqueia_referencia_com_caixa_diferente(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        db.session.add(Produto(codigo='REF-30', nome='Produto 30', preco=10, etiqueta='TESTE', imagem_url=''))
        db.session.commit()
        db.session.add(Produto(codigo='ref-30', nome='Duplicado', preco=10, etiqueta='TESTE', imagem_url=''))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        assert Produto.query.count() == 1


def test_uploads_rejeitam_pdf_e_arquivo_disfarçado_de_imagem():
    pdf = FileStorage(stream=BytesIO(b'%PDF-1.7 arquivo'), filename='catalogo.pdf', content_type='application/pdf')
    pdf_disfarçado = FileStorage(stream=BytesIO(b'%PDF-1.7 arquivo'), filename='catalogo.jpg', content_type='image/jpeg')

    with pytest.raises(ValueError, match='somente imagens'):
        validar_arquivos_imagem([pdf])
    with pytest.raises(ValueError, match='imagem válida'):
        validar_arquivos_imagem([pdf_disfarçado])


def test_upload_jpeg_valido_e_aceito_com_stream_rebobinado():
    conteudo = BytesIO()
    Image.new('RGB', (1, 1), color='red').save(conteudo, format='JPEG')
    conteudo.seek(0)
    upload = FileStorage(stream=conteudo, filename='produto.jpg', content_type='image/jpeg')

    assert validar_arquivos_imagem([upload]) == [upload]
    assert upload.stream.tell() == 0


def test_api_exclui_imagem_ativa_e_mantem_outra_imagem(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.app_context():
        produto = Produto(
            codigo='IMG-77', nome='Produto com fotos', preco=99, etiqueta='TESTE', imagem_url='uploads/primeira.jpg'
        )
        db.session.add(produto)
        db.session.commit()
        img1 = ProdutoImagem(produto=produto, imagem_url='uploads/primeira.jpg', ordem=0)
        img2 = ProdutoImagem(produto=produto, imagem_url='uploads/segunda.jpg', ordem=1)
        db.session.add_all([img1, img2])
        db.session.commit()
        produto_id = produto.id
        imagem_id = img1.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(f'/api/admin/produtos/{produto_id}/imagens/{imagem_id}/excluir')

    assert resposta.status_code == 200
    resposta_json = resposta.get_json()
    assert resposta_json['sucesso'] is True

    with app.app_context():
        produto_atualizado = Produto.query.get(produto_id)
        assert produto_atualizado.imagem_url == 'uploads/segunda.jpg'
        assert ProdutoImagem.query.filter_by(produto_id=produto_id).count() == 1


def test_imagem_disponivel_detecta_assets_e_ignora_caminhos_ausentes(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        assert imagem_disponivel('img/banner_hero1.jpeg')
        assert not imagem_disponivel('uploads/arquivo-que-nao-existe.pdf.gallery.webp')
        assert not imagem_disponivel('../instance/image-originals/banner_hero1.jpg')
