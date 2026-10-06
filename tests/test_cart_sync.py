import json

from app import create_app, db
from app.models import Produto, Usuario


def test_sync_carrinho_identifica_item_indisponivel(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app()
    app.config['TESTING'] = True

    with app.app_context():
        usuario = Usuario(
            nome='Cliente teste',
            email='carrinho-indisponivel@teste.com',
            senha='senha',
            whatsapp='81999999999',
        )
        produto = Produto(
            codigo='INDISPONIVEL',
            nome='Blusa de manga tule',
            preco=20,
            etiqueta='TESTE',
            imagem_url='',
            grade=json.dumps([{'nome': 'M', 'estoque': 0, 'preco': 20}]),
        )
        db.session.add_all([usuario, produto])
        db.session.commit()
        usuario_id = usuario.id
        produto_id = produto.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(usuario_id)
            sess['_fresh'] = True

        resposta = client.post('/api/carrinho/sync', json={
            'carrinho': [{
                'cartId': f'{produto_id}_sem-cor_M',
                'id': produto_id,
                'nome': 'Blusa de manga tule',
                'tamanho': 'M',
                'cor': None,
                'quantidade': 1,
                'preco': 20,
            }],
        })

    dados = resposta.get_json()
    assert dados['sucesso'] is False
    assert dados['item_indisponivel'] == {
        'cart_id': f'{produto_id}_sem-cor_M',
        'id': produto_id,
        'tamanho': 'M',
        'cor': None,
        'quantidade': 1,
    }
