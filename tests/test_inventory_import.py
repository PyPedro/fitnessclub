import json
import sys

from app import create_app, db
from app.models import ImportacaoEstoque, Produto
from scripts import importar_estoque
from scripts.importar_estoque import criar_produto_sem_cadastro, ler_inventario, planejar_importacao
from app.routes import chave_cor, cor_para_hex, nome_cor, variantes_com_cor_hex


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


def test_vitrine_mostra_placeholder_para_produto_sem_imagem(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    with app.app_context():
        db.session.add(Produto(
            codigo='473',
            nome='Conj short saia e top',
            preco=0,
            etiqueta='NOVO',
            imagem_url='',
            cores=json.dumps(['Azul marinho']),
            variantes=json.dumps([{'cor': 'Azul marinho', 'tamanhos': [{'nome': 'M', 'estoque': 7, 'preco': 0}]}]),
        ))
        db.session.commit()

    resposta = app.test_client().get('/')
    html = resposta.get_data(as_text=True)
    assert resposta.status_code == 200
    assert 'Foto não cadastrada' in html
    assert 'src="/static/"' not in html


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
