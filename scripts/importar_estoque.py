import argparse
import json
import re
import sys
import unicodedata
from collections import OrderedDict
from pathlib import Path

from app import create_app, db
from app.models import ImportacaoEstoque, Produto


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_FILE = ROOT / 'data' / 'inventario-inicial.txt'
IMPORT_KEY = 'inventario-inicial-2026-09-v1'
SIZES = {'P', 'M', 'G', 'GG', 'GG2'}
HEADER_PATTERN = re.compile(r'^(.+?)\s+(?:ref\s*)?(\d{3})$', re.IGNORECASE)
STOCK_PATTERN = re.compile(r'^(\d+)\s*(.+)$')


def texto_chave(value):
    value = unicodedata.normalize('NFKD', str(value or ''))
    value = ''.join(char for char in value if not unicodedata.combining(char))
    return re.sub(r'\s+', ' ', value).strip().casefold()


def referencia_chave(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return digits.lstrip('0') or '0' if digits else ''


def ler_inventario():
    produtos = OrderedDict()
    produto_atual = None
    tamanho_atual = None

    def finalizar_produto():
        if produto_atual is None:
            return
        referencia = produto_atual['referencia']
        anterior = produtos.get(referencia)
        if anterior is None:
            produtos[referencia] = produto_atual.copy()
            return
        if texto_chave(anterior['nome']) != texto_chave(produto_atual['nome']) or anterior['estoque'] != produto_atual['estoque']:
            raise ValueError(f'Referencia {referencia} aparece mais de uma vez com dados diferentes.')

    for numero, linha_original in enumerate(INVENTORY_FILE.read_text(encoding='utf-8').splitlines(), start=1):
        linha = linha_original.strip()
        if not linha or linha.startswith('#'):
            continue

        cabecalho = HEADER_PATTERN.fullmatch(linha)
        if cabecalho:
            finalizar_produto()
            produto_atual = {
                'nome': cabecalho.group(1).strip(),
                'referencia': cabecalho.group(2),
                'estoque': OrderedDict(),
            }
            tamanho_atual = None
            continue

        if produto_atual is None:
            raise ValueError(f'Linha {numero}: esperava nome e referencia do produto.')

        if linha.upper() in SIZES:
            tamanho_atual = linha.upper()
            produto_atual['estoque'].setdefault(tamanho_atual, OrderedDict())
            continue

        item = STOCK_PATTERN.fullmatch(linha)
        if not item or tamanho_atual is None:
            raise ValueError(f'Linha {numero}: linha de estoque invalida: {linha_original!r}.')

        quantidade = int(item.group(1))
        cor = re.sub(r'\s+', ' ', item.group(2).strip().rstrip('.')).strip().title()
        if not cor or quantidade < 0:
            raise ValueError(f'Linha {numero}: cor ou quantidade invalida.')
        estoque_cor = produto_atual['estoque'][tamanho_atual]
        chave_cor = texto_chave(cor)
        cor_existente = next((nome for nome in estoque_cor if texto_chave(nome) == chave_cor), None)
        if cor_existente is None:
            estoque_cor[cor] = quantidade
        else:
            estoque_cor[cor_existente] += quantidade

    finalizar_produto()
    return list(produtos.values())


def localizar_produto(produtos_db, item):
    referencia_item = referencia_chave(item['referencia'])
    por_referencia = [
        produto for produto in produtos_db
        if referencia_chave(produto.codigo) == referencia_item
    ]
    if len(por_referencia) == 1:
        return por_referencia[0], 'referencia'
    if len(por_referencia) > 1:
        return None, 'referencia duplicada no catalogo'

    por_nome = [produto for produto in produtos_db if texto_chave(produto.nome) == texto_chave(item['nome'])]
    if len(por_nome) == 1:
        return por_nome[0], 'nome exato (codigo divergente)'
    if len(por_nome) > 1:
        return None, 'nome ambiguo e referencia ausente'
    return None, 'produto ausente'


def montar_variantes(produto, item):
    variantes_anteriores = produto.variantes_config
    precos_anteriores = {}
    precos_por_tamanho = {}
    for variante in variantes_anteriores:
        for tamanho in variante.get('tamanhos', []):
            chave = (texto_chave(variante.get('cor')), texto_chave(tamanho.get('nome')))
            precos_anteriores[chave] = tamanho.get('preco')
            precos_por_tamanho.setdefault(texto_chave(tamanho.get('nome')), tamanho.get('preco'))
    for tamanho in produto.grade_config:
        precos_por_tamanho.setdefault(texto_chave(tamanho.get('nome')), tamanho.get('preco'))

    variantes = OrderedDict()
    for nome_tamanho, cores in item['estoque'].items():
        for cor, quantidade in cores.items():
            tamanhos = variantes.setdefault(cor, [])
            chave_preco = (texto_chave(cor), texto_chave(nome_tamanho))
            preco = precos_anteriores.get(chave_preco) or precos_por_tamanho.get(texto_chave(nome_tamanho)) or produto.preco
            tamanhos.append({
                'nome': nome_tamanho,
                'estoque': quantidade,
                'preco': float(preco),
            })

    return [{'cor': cor, 'tamanhos': tamanhos} for cor, tamanhos in variantes.items()]


def main():
    parser = argparse.ArgumentParser(description='Importa o estoque inicial por referencia, cor e tamanho.')
    parser.add_argument('--apply', action='store_true', help='Grava no banco; sem esta opcao, apenas valida.')
    args = parser.parse_args()

    inventario = ler_inventario()
    app = create_app()
    with app.app_context():
        if db.session.get(ImportacaoEstoque, IMPORT_KEY):
            print(f'Importacao {IMPORT_KEY} ja executada; nenhuma alteracao feita.')
            return 0

        produtos_db = Produto.query.all()
        correspondencias = []
        problemas = []
        for item in inventario:
            produto, metodo = localizar_produto(produtos_db, item)
            if produto is None:
                problemas.append(f"Ref {item['referencia']} ({item['nome']}): {metodo}.")
            else:
                correspondencias.append((item, produto, metodo))

        print(f'Produtos na importacao: {len(inventario)}')
        for item, produto, metodo in correspondencias:
            print(f"Ref {item['referencia']} -> {produto.codigo or '(sem codigo)'} / {produto.nome} [{metodo}]")
        if problemas:
            print('Importacao cancelada; referencias sem correspondencia unica:')
            for problema in problemas:
                print(f'- {problema}')
            return 2

        if not args.apply:
            print('Validacao concluida sem gravar. Execute com --apply para importar uma unica vez.')
            return 0

        try:
            for item, produto, _ in correspondencias:
                variantes = montar_variantes(produto, item)
                produto.variantes = json.dumps(variantes, ensure_ascii=False)
                produto.cores = json.dumps([variante['cor'] for variante in variantes], ensure_ascii=False)
                produto.grade = json.dumps(variantes[0]['tamanhos'] if variantes else [], ensure_ascii=False)
                for tamanho in ('p', 'm', 'g', 'gg'):
                    setattr(produto, f'estoque_{tamanho}', sum(
                        int(item_tamanho['estoque'])
                        for variante in variantes
                        for item_tamanho in variante['tamanhos']
                        if item_tamanho['nome'].casefold() == tamanho.upper().casefold()
                    ))

            db.session.add(ImportacaoEstoque(chave=IMPORT_KEY))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        print(f'Importacao concluida: {len(correspondencias)} produtos atualizados.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
