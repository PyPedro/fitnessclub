import csv
import io
import json

from app import create_app, db
from app.models import Produto


def _criar_csv(linhas, campos=None, delimitador=';'):
    buffer = io.StringIO()
    campos = campos or [
        'Nome', 'Preço', 'referencia', 'Estoque-Saldo',
        'Variacao1', 'Variavel1', 'Variacao2', 'Variavel2',
        'Variacao3', 'Variavel3', 'Variacao4', 'Variavel4',
    ]
    escritor = csv.DictWriter(buffer, fieldnames=campos, delimiter=delimitador)
    escritor.writeheader()
    escritor.writerows(linhas)
    return io.BytesIO(buffer.getvalue().encode('utf-8-sig'))


def test_importar_csv_cria_produtos_com_variantes_e_estoque(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    linhas = [
        {
            'Nome': 'Produto de teste', 'Preço': '29.90', 'referencia': 'CSV-001',
            'Estoque-Saldo': '3', 'Variacao1': 'GRADE', 'Variavel1': 'M',
            'Variacao2': 'Cores disponíveis', 'Variavel2': 'Azul',
        },
        {
            'Nome': 'Produto de teste', 'Preço': '29.90', 'referencia': 'CSV-001',
            'Estoque-Saldo': '4', 'Variacao1': 'GRADE', 'Variavel1': 'G',
            'Variacao2': 'Cores disponíveis', 'Variavel2': 'Preto',
        },
    ]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/admin/importar-csv',
            data={'arquivo': (_criar_csv(linhas), 'produtos.csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    assert '1 produtos importados' in resposta.get_data(as_text=True)
    with app.app_context():
        produto = Produto.query.filter_by(codigo='CSV-001').one()
        assert produto.preco == 29.90
        assert produto.estoque_m == 3
        assert produto.estoque_g == 4
        assert json.loads(produto.cores) == ['Azul', 'Preto']
        variantes = json.loads(produto.variantes)
        assert variantes == [
            {'cor': 'Azul', 'tamanhos': [{'nome': 'M', 'estoque': 3, 'preco': 29.9}]},
            {'cor': 'Preto', 'tamanhos': [{'nome': 'G', 'estoque': 4, 'preco': 29.9}]},
        ]


def test_importa_formato_exportado_completo_com_colunas_extras_e_csv_excel(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    campos = [
        'Nome', 'Preço', 'Descrição', 'referencia', 'Categoria',
        'Embalagem-Largura', 'Embalagem-Altura', 'Embalagem-Comprimento',
        'Embalagem-Peso', 'Embalagem-Transporte', 'Estoque-Saldo',
        'Variacao1', 'Variavel1', 'Variacao2', 'Variavel2',
        'Variacao3', 'Variavel3', 'Variacao4', 'Variavel4',
        'Fiscal-NCM', 'Fiscal-CEST', 'Fiscal-Origem', 'Fiscal-Unidade',
        'Fiscal-PesoLiquido', 'Fiscal-PesoBruto',
    ]
    linhas = [{
        'Nome': 'Calça jeans teste', 'Preço': '62,00',
        'Descrição': '<p>Produto, descrição</p>', 'referencia': 'CSV-004',
        'Categoria': 'Jeans masculino', 'Embalagem-Largura': '35',
        'Embalagem-Altura': '3', 'Embalagem-Comprimento': '32',
        'Embalagem-Peso': '1.00', 'Embalagem-Transporte': 'caixa',
        'Estoque-Saldo': '77', 'Variacao1': 'GRADS', 'Variavel1': '40',
        'Variacao2': '', 'Variavel2': '',
    }]
    arquivo = _criar_csv(linhas, campos=campos, delimitador=',').getvalue().decode('utf-8-sig').encode('cp1252')

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/admin/importar-csv?formato=json',
            data={'arquivo': (io.BytesIO(arquivo), 'produtos.csv')},
            content_type='multipart/form-data',
        )

    assert resposta.status_code == 200
    assert resposta.get_json()['sucesso'] is True
    with app.app_context():
        produto = Produto.query.filter_by(codigo='CSV-004').one()
        assert produto.preco == 62
        assert json.loads(produto.grade) == [{'nome': '40', 'estoque': 77, 'preco': 62}]


def test_importar_csv_falha_sem_gravar_se_houver_dado_invalido(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    linhas = [{
        'Nome': 'Produto inválido', 'Preço': 'valor inválido', 'referencia': 'CSV-002',
        'Estoque-Saldo': '5', 'Variacao1': 'GRADE', 'Variavel1': 'M',
    }]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/admin/importar-csv',
            data={'arquivo': (_criar_csv(linhas), 'produtos.csv')},
            content_type='multipart/form-data',
            follow_redirects=True,
        )

    assert resposta.status_code == 200
    assert 'Não foi possível importar o CSV' in resposta.get_data(as_text=True)
    with app.app_context():
        assert Produto.query.filter_by(codigo='CSV-002').count() == 0


def test_importacao_em_lote_aceita_csv_e_retorna_json(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    linhas = [{
        'Nome': 'Produto do botão em lote', 'Preço': '15.00', 'referencia': 'CSV-003',
        'Estoque-Saldo': '2', 'Variacao1': 'GRADE', 'Variavel1': 'P',
    }]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/admin/importar-csv?formato=json',
            data={'arquivo': (_criar_csv(linhas), 'produtos.csv')},
            content_type='multipart/form-data',
        )

    assert resposta.status_code == 200
    assert resposta.get_json() == {
        'sucesso': True,
        'mensagem': 'Importação concluída com sucesso: 1 produtos importados.',
        'produtos': 1,
    }
    with app.app_context():
        assert Produto.query.filter_by(codigo='CSV-003').one().estoque_p == 2


def test_rota_importacao_estoque_encaminha_csv_e_ignora_colunas_extras(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True
    campos = [
        'Nome', 'Preço', 'referencia', 'Estoque-Saldo',
        'Variacao1', 'Variavel1', 'Variacao2', 'Variavel2', 'Coluna extra', '',
    ]
    linhas = [
        {
            'Nome': 'Produto com valores brasileiros', 'Preço': '1.234,50',
            'referencia': 'CSV-005', 'Estoque-Saldo': '77,0',
            'Variacao1': 'GRADE', 'Variavel1': '40',
            'Coluna extra': 'ignorar este conteúdo',
        },
        {
            'Nome': 'Produto com valores vazios', 'Preço': '',
            'referencia': 'CSV-006', 'Estoque-Saldo': '',
            'Variacao1': 'GRADE', 'Variavel1': 'M',
        },
    ]

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/api/admin/importar-estoque',
            data={'arquivo': (_criar_csv(linhas, campos=campos), 'produtos.CSV')},
            content_type='multipart/form-data',
        )

    assert resposta.status_code == 200
    assert resposta.get_json()['sucesso'] is True
    with app.app_context():
        produto_brasileiro = Produto.query.filter_by(codigo='CSV-005').one()
        produto_vazio = Produto.query.filter_by(codigo='CSV-006').one()
        assert produto_brasileiro.preco == 1234.5
        assert json.loads(produto_brasileiro.grade) == [
            {'nome': '40', 'estoque': 77, 'preco': 1234.5},
        ]
        assert produto_vazio.preco == 0
        assert json.loads(produto_vazio.grade) == [
            {'nome': 'M', 'estoque': 0, 'preco': 0},
        ]


def test_rota_importacao_registra_erro_tecnico_de_linha_txt(monkeypatch, caplog):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.post(
            '/api/admin/importar-estoque',
            data={
                'arquivo': (
                    io.BytesIO(
                        b'Nome;Pre\xc3\xa7o;referencia;Estoque-Saldo\n'
                        b'Produto de teste;10.00;007;5\n'
                    ),
                    'estoque.txt',
                ),
            },
            content_type='multipart/form-data',
        )

    assert resposta.status_code == 500
    assert 'Erro técnico ao importar arquivo de estoque.' in caplog.text
    assert 'linha de estoque invalida' in caplog.text
    assert 'Produto de teste;10.00;007;5' in caplog.text


def test_formulario_de_importacao_csv_no_painel(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['admin_logado'] = True
        resposta = client.get('/admin')

    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert 'action="/admin/importar-csv"' in html
    assert 'enctype="multipart/form-data"' in html
    assert 'type="file" accept=".csv" name="arquivo" required' in html
    assert 'Importar CSV' in html
    assert "arquivo.name.toLocaleLowerCase().endsWith('.csv')" in html
    assert "'/admin/importar-csv?formato=json' : '/api/admin/importar-estoque'" in html
