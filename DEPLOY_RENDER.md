# Deploy no Render

## Antes de publicar

1. Crie um banco PostgreSQL no Render, de preferência na mesma região do serviço web, e copie a Internal Database URL.
2. Crie ou atualize o serviço usando o Blueprint deste repositório (`render.yaml`). O plano `starter` e o disco persistente de 1 GB têm custo no Render.
3. Preencha as variáveis marcadas como secretas durante a configuração do Blueprint:
   - `DATABASE_URL`: Internal Database URL do PostgreSQL.
   - `ADMIN_EMAIL` e `ADMIN_PASSWORD`: credenciais fortes para o painel inicial.
   - `MERCADO_PAGO_ACCESS_TOKEN`: token de produção do Mercado Pago.
4. Confirme `SECRET_KEY` (gerada pelo Render), `UPLOAD_DIR=/var/data/uploads` e `WHATSAPP_LOJA` nas variáveis do serviço.
5. Faça o deploy e abra a loja. Na primeira requisição, o sistema cria as tabelas e o administrador inicial usando as credenciais configuradas.

O administrador só é criado automaticamente se ainda não existir nenhum registro e as duas variáveis `ADMIN_EMAIL` e `ADMIN_PASSWORD` estiverem definidas. Defina-as antes do primeiro acesso; alterar as variáveis depois não troca a senha de uma conta já criada.

## Importar estoque inicial

Depois de publicar o código, abra o Shell do serviço Web no Render e execute primeiro a validação:

```powershell
python -m scripts.importar_estoque
```

O comando confere as 38 referências com o catálogo existente e não grava dados. Se alguma referência estiver ausente ou ambígua, a importação é cancelada; corrija o cadastro/código do produto antes de continuar. Quando todas as correspondências estiverem corretas, execute uma única vez:

```powershell
python -m scripts.importar_estoque --apply
```

A carga atualiza cores, tamanhos e quantidades, preserva nomes, imagens e preços existentes, e registra sua execução para impedir reaplicação acidental.

## Persistência e pagamentos

O PostgreSQL guarda produtos, clientes e pedidos. As imagens enviadas pelo painel são gravadas no disco montado em `/var/data`, portanto esse disco precisa permanecer anexado ao serviço. Os arquivos estáticos incluídos no repositório continuam sendo servidos normalmente.

O checkout só inicia quando `MERCADO_PAGO_ACCESS_TOKEN` contém o token correspondente ao ambiente de produção. `WHATSAPP_LOJA` deve conter o número da loja com código do país, apenas dígitos.

Não use o SQLite local como banco de produção: o sistema de arquivos do serviço web é efêmero e não é compartilhado entre instâncias.