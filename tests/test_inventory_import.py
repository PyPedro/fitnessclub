from scripts.importar_estoque import ler_inventario
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
