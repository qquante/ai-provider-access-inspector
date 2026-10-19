# FoundLLM KeyScope

CLI Python, sem dependências externas, para auditar chaves de 10 provedores de IA. A ferramenta faz somente requisições HTTP `GET` oficiais: valida a credencial, identifica a conta quando a API permite, lista os modelos visíveis e mostra saldo/uso apenas quando o provedor realmente expõe esses dados.

Ela **não envia prompts, não cria recursos, não faz inferência paga e não imprime nem grava as chaves**. O relatório contém apenas o nome da variável usada e um fingerprint SHA-256 curto para correlação local.

## Uso rápido no Windows/PowerShell

Requer Python 3.10 ou mais recente.

```powershell
Copy-Item .env.example .env
notepad .env
python .\key_audit.py
```

Preencha somente as chaves que você possui. `.env` já está ignorado pelo Git.

Gerar um relatório JSON:

```powershell
python .\key_audit.py --output .\reports\keys.json --summary-only
```

Auditar provedores específicos e guardar todos os modelos retornados:

```powershell
python .\key_audit.py --provider openai deepseek openrouter --models-limit 0
```

Saída JSON no terminal:

```powershell
python .\key_audit.py --json
```

## Variáveis aceitas

As variáveis canônicas são:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
OPENROUTER_API_KEY
GROQ_API_KEY
CEREBRAS_API_KEY
MISTRAL_API_KEY
DEEPSEEK_API_KEY
TOGETHER_API_KEY
HF_TOKEN
REPLICATE_API_TOKEN
```

Também são aceitos exatamente os nomes informados no pedido:

```text
openai_proj
anthropic_api_key
openrouter_api_key
groq_api_key
cerebras_api_key_context
mistral_api_key_context
deepseek_api_key_context
together_api_key_context
huggingface
replicate_api_token
```

Variáveis já definidas no processo têm precedência sobre o arquivo `.env`.

## O que é possível obter oficialmente

Pesquisa revisada em 30 de agosto de 2026.

| Provedor | Validação/modelos | Saldo/uso com a chave informada | Limite real |
|---|---|---|---|
| OpenAI | `GET /v1/models` | Chave de projeto não expõe saldo. A API administrativa expõe custos, não saldo pré-pago. | Não certifica crédito disponível sem uma chamada faturável. |
| Anthropic | `GET /v1/models` | Chave comum não expõe saldo; custo/uso requer credencial Admin. | Não certifica crédito disponível sem uma chamada faturável. |
| OpenRouter | `GET /api/v1/key` + `/models` | Chave comum mostra uso/limite próprio. `/credits` mostra saldo total somente para Management API Key. | “limit_remaining” é limite da chave, não necessariamente saldo da conta. |
| Groq | `GET /openai/v1/models` | Sem endpoint público oficial documentado de saldo para chave de inferência. | Billing no Console GroqCloud. |
| Cerebras | `GET /v1/models`; metadados públicos em `/public/v1/models` | Sem endpoint público oficial documentado de saldo. | Preço/capacidades vêm do catálogo público, saldo fica no painel. |
| Mistral | `GET /v1/models` | Uso e spend limit exigem Admin API Key; créditos ficam no painel. | Chave comum não lê billing. |
| DeepSeek | `GET /user/balance` + `/models` | Expõe saldo total, concedido, recarregado e `is_available`. | É o saldo real retornado pela API oficial. |
| Together AI | `GET /v1/models` | Saldo e analytics são documentados no painel, sem endpoint público oficial para chave comum. | O catálogo inclui preços brutos retornados pela API. |
| Hugging Face | `GET /api/whoami-v2` + router `/v1/models` | Billing/credits de Inference Providers ficam no painel. | Token pode ser válido no Hub e não ter permissão de inference; isso vira resultado parcial. |
| Replicate | `GET /v1/account` + `/v1/models` | A API oficial não expõe saldo. | A listagem de modelos é paginada; o relatório marca a contagem como parcial. |

Fontes oficiais usadas no código e na análise:

- [OpenAI Models API](https://developers.openai.com/api/reference/resources/models) e [Organization Usage/Costs](https://developers.openai.com/api/reference/resources/admin/subresources/organization/subresources/usage)
- [Anthropic Models API](https://platform.claude.com/docs/en/api/models/list) e [Cost Report](https://platform.claude.com/docs/en/api/admin/cost_report/retrieve)
- [OpenRouter current key](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key), [credits](https://openrouter.ai/docs/api/api-reference/credits/get-credits) e [models](https://openrouter.ai/docs/api/api-reference/models/get-models)
- [Groq supported models](https://console.groq.com/docs/models)
- [Cerebras list models](https://inference-docs.cerebras.ai/api-reference/models/list-models) e [public model metadata](https://inference-docs.cerebras.ai/api-reference/models/public-models)
- [Mistral models](https://docs.mistral.ai/api/endpoint/models) e [Admin usage](https://docs.mistral.ai/admin/admin-api/usage-metrics)
- [DeepSeek balance](https://api-docs.deepseek.com/api/get-user-balance/) e [models](https://api-docs.deepseek.com/api/list-models/)
- [Together models](https://docs.together.ai/reference/models) e [credits](https://docs.together.ai/docs/billing-credits)
- [Hugging Face tokens](https://huggingface.co/docs/hub/security-tokens), [Inference Providers](https://huggingface.co/docs/inference-providers/en/index) e [pricing/billing](https://huggingface.co/docs/inference-providers/pricing)
- [Replicate HTTP API](https://replicate.com/docs/reference/http/) e [billing](https://replicate.com/docs/topics/billing)

Os campos de preço são preservados no formato bruto de cada API. **Não compare os números entre provedores sem consultar a unidade documentada por cada um**: alguns retornam preço por token, outros por milhão de tokens ou por unidade de compute.

## Status e códigos de saída

- `VÁLIDA`: endpoint autenticado respondeu e os modelos foram lidos.
- `VÁLIDA/PARCIAL`: a chave foi validada, mas uma consulta opcional (modelos, saldo ou metadados) falhou.
- `INVÁLIDA`: HTTP 401 no endpoint de validação.
- `RESTRITA`: HTTP 403; a credencial pode existir, mas o escopo não permite confirmar a operação.
- `LIMITADA`: HTTP 429 durante a validação.
- `INDISPONÍVEL`: erro de rede, timeout, resposta inválida ou falha do provedor.
- `NÃO CONFIGURADA`: nenhuma variável aceita foi encontrada.

Códigos do processo:

- `0`: todas as chaves configuradas passaram (resultados parciais geram avisos).
- `1`: houve chave inválida, restrita, limitada ou provedor indisponível.
- `2`: nenhuma chave foi configurada.

Use `--strict-missing` para também falhar quando uma chave selecionada estiver ausente.

## Segurança

- Apenas hosts oficiais fixos no código são chamados.
- Redirecionamento para outro host é bloqueado para impedir vazamento do header de autorização.
- Chaves não aparecem em logs, tabela ou JSON; respostas são redigidas novamente antes da saída.
- Nenhum endpoint `POST`, geração, fine-tuning, criação ou cobrança é usado.
- `.env`, `.env.*` e `reports/` são ignorados pelo Git.
- O JSON ainda pode conter nome de conta, saldo, uso e modelos privados; trate-o como informação sensível.
- Uma chave válida para listar modelos não prova que há saldo, quota ou permissão para executar cada modelo. O programa não faz uma chamada paga para provar isso.

## Testes

Todos os testes são offline e usam respostas simuladas; nenhuma chave real é necessária.

```powershell
python -m unittest discover -s tests -v
```
