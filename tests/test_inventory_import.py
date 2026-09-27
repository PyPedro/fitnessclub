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

    assert len(inventario) == 38
    assert sum(item['referencia'] == '459' for item in inventario) == 1
    assert sum(
        quantidade
        for item in inventario
        for cores in item['estoque'].values()
        for quantidade in cores.values()
    ) == 4598


def test_inventario_soma_cores_repetidas_e_preserva_tamanho_especial():
    inventario = {item['referencia']: item for item in ler_inventario()}

    assert inventario['523']['estoque']['M']['Açaí'] == 5
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


def test_cores_nomeadas_preservam_cor_de_pedidos_legados():
    assert cor_para_hex('Pink Cereja') == '#c51e62'
    assert nome_cor('#1c1c1a') == 'Preto'
    assert chave_cor('#172b4d') == chave_cor('Azul marinho')
    assert nome_cor('#123456') == 'Personalizada (#123456)'
    variante = variantes_com_cor_hex([{'cor': 'Azul marinho', 'tamanhos': []}])[0]
    assert variante['cor'] == 'Azul marinho'
    assert variante['cor_hex'] == '#172b4d'
    assert variante['cor_nome'] == 'Azul marinho'


def test_cria_produto_novo_com_preco_zero_sem_imagem_e_grade_completa():
    inventario = {item['referencia']: item for item in ler_inventario()}
    produto = criar_produto_sem_cadastro(inventario['366'])

    assert produto.codigo == '366'
    assert produto.nome == 'Short duplo plus size'
    assert produto.preco == 0
    assert produto.imagem_url == ''
    assert produto.estoque_gg == 19
    assert {'cor': 'Branco', 'tamanhos': [{'nome': 'GG2', 'estoque': 19, 'preco': 0.0}]} in json.loads(produto.variantes)


def test_catalogo_vazio_planeja_criacao_das_38_referencias():
    correspondencias, problemas = planejar_importacao([], ler_inventario())

    assert len(correspondencias) == 38
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


def test_apply_cria_38_produtos_e_nao_duplica_na_reexecucao(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    monkeypatch.setattr(importar_estoque, 'create_app', lambda: app)
    monkeypatch.setattr(sys, 'argv', ['scripts.importar_estoque', '--apply'])

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 38
        produto = Produto.query.filter_by(codigo='056').one()
        assert produto.preco == 0
        assert produto.imagem_url == ''
        assert ImportacaoEstoque.query.count() == 1

    assert importar_estoque.main() == 0
    with app.app_context():
        assert Produto.query.count() == 38


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
