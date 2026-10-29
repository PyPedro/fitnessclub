import csv
import io
import json

from app import create_app, db
from app.models import Produto


def _criar_csv(linhas):
    buffer = io.StringIO()
    campos = [
        'Nome', 'Preço', 'referencia', 'Estoque-Saldo',
        'Variacao1', 'Variavel1', 'Variacao2', 'Variavel2',
        'Variacao3', 'Variavel3', 'Variacao4', 'Variavel4',
    ]
    escritor = csv.DictWriter(buffer, fieldnames=campos, delimiter=';')
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
