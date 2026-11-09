# Navis-mcp

*Read in English: [README.md](README.md)*

Um único servidor MCP para o **Autodesk Navisworks Manage 2025 e 2027**. Ele junta, num processo e num executável só:

- **`navis_*`** (do [NavisCoord](https://github.com/HorizunGroup/naviscoord-mcp)), para coordenação e clash: ranking de interferências, grupos, causa raiz, plano de trabalho, relatórios em PDF, snapshots e comparação entre rodadas.
- **`nwd_*`** (port em Python do [nwd-mcp](https://github.com/bimwright/nwd-mcp)), para consulta geral do modelo: documento, árvore, propriedades, busca, sets e viewpoints.

Funciona com Claude Code, Claude Desktop ou qualquer cliente MCP por stdio.

## Como funciona

```
Cliente MCP ──stdio──► navis-mcp.exe (Python, um processo)
                         ├─ navis_*  ──HTTP loopback──► add-in NavisCoord ─┐
                         └─ nwd_*    ──TCP  loopback──► plug-in nwd ───────┴─► Navisworks Manage 2025 / 2027
```

O servidor do nwd-mcp, originalmente em C#/.NET 8, foi reescrito em Python dentro do servidor do NavisCoord. Ele fala o mesmo protocolo com o mesmo plug-in. Os dois add-ins continuam em C# e rodam dentro do Navisworks.

## Modo leitura (padrão)

O servidor sobe **somente leitura**, e uma chave só vale para as duas partes:

- o NavisCoord recusa qualquer rota de escrita;
- `navis_save`, `navis_save_as`, `navis_close_document` e `navis_exit` nem aparecem;
- as ferramentas `nwd_*` de escrita não são registradas (`nwd_send_code`, abrir ou importar arquivo, ocultar, viewpoints, ToolBaker).

No modo leitura ficam 70 ferramentas: 49 `navis_*` e 21 `nwd_*`. Para liberar a escrita, use `--allow-write` ou `NAVIS_MCP_READ_ONLY=0`.

## Modo escrita (`--allow-write`)

Testado ao vivo no Navisworks Manage 2025 e 2027, em cópias de um federado real:

| Tarefa | Ferramentas |
|---|---|
| Criar testes de clash | `navis_load_profile("og7")` → `navis_configure` (um conjunto por disciplina + a matriz de testes) |
| Rodar testes | `navis_run` (todos, em segundo plano; acompanhe com `navis_job_status`) ou `navis_run_tests` |
| Analisar | `navis_analyze` |
| Mudar status | `navis_set_status` (Novo / Ativo / Revisado / Aprovado / Resolvido) |
| Colorir o modelo | `navis_color_by_priority`; desfazer com `navis_reset_appearance` |
| Salvar o NWD | `navis_save_as` num nome **novo** (próxima revisão, ex.: `-R01.nwd`) |
| Fechar / sair | `navis_close_document`, `navis_exit` (`require_clean` ou `discard`) |
| Mexer no modelo (nwd) | ocultar/mostrar, salvar viewpoint, abrir/importar arquivo, ToolBaker |

Toda escrita confere a "huella" do documento (lida em `navis_health`), e a maioria começa em `dry_run=true`: mostra o plano antes de mudar qualquer coisa.

Duas coisas continuam travadas mesmo no modo escrita, cada uma com a sua chave:

- **Sobrescrever** (`--allow-overwrite` / `NAVIS_MCP_ALLOW_OVERWRITE=1`): sem ela, `navis_save` (salvar por cima) fica oculto, `navis_save_as` recusa `overwrite=true` e fechar/sair recusam `disposition="save"`. Rodada nova é revisão nova, nunca arquivo salvo por cima.
- **Código arbitrário** (`--allow-send-code` / `NAVIS_MCP_SEND_CODE=1`): `nwd_send_code` roda qualquer C# dentro do Navisworks.

No modo escrita ficam 84 ferramentas (52 `navis_*`, 32 `nwd_*`). A cópia pode ser salva na pasta do documento aberto, em `%LOCALAPPDATA%\NavisCoord\exports` ou nas pastas de `NAVISCOORD_OUTPUT_ROOTS` (`navis_output_policy` mostra quais).

### Perfil OG7

`navis_load_profile("og7")` carrega o perfil do projeto (`server/naviscoord/profiles/og7.json`, gerado por `scripts/make_og7_profile.py`): os códigos de disciplina do OG7 (ARQ, EST, HID, ESG, ELE, INC, GAS, ARC) lidos do nome de cada arquivo, as categorias do Revit em português e 19 pares de disciplinas com nomes como `EST X ESG`. Cada conjunto pega toda peça cujo `Item > Source File` contém `-CÓDIGO-`, então funciona no NWD publicado (que abre como um modelo só) e num NWF com os NWC anexados. Os nomes de propriedade são os que o Navisworks mostra em inglês.

## Instalar

Com o Navisworks **fechado**:

```powershell
# a partir do ZIP do release ou da pasta dist\Navis-mcp
powershell -ExecutionPolicy Bypass -File .\install.ps1 -RegisterClaudeCode
```

Isso instala:

| O quê | Onde |
|---|---|
| add-in NavisCoord | `%APPDATA%\Autodesk\ApplicationPlugins\NavisCoord.bundle` (2025 e 2027; o NW 2027 não carrega mais add-ins da pasta `Plugins` por usuário) |
| plug-in nwd | `%APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle` |
| servidor MCP | `%LOCALAPPDATA%\Navis-mcp\server-1.1.0\navis-mcp.exe` (uma pasta por versão, para um cliente MCP aberto nunca travar a atualização) |

Se preferir registrar à mão no Claude Code (acrescente `--allow-write` no fim para o modo escrita):

```powershell
claude mcp add --transport stdio --scope user navisworks -- "$env:LOCALAPPDATA\Navis-mcp\server-1.1.0\navis-mcp.exe"
```

Se o Navisworks estiver aberto e só o servidor mudou, `install.ps1 -ServerOnly` instala só o servidor novo. Depois reinicie o cliente MCP.

Depois, abra o Navisworks (2025 ou 2027) com o modelo e peça: *"chama navis_health e nwd_health_check e analisa os clashes sem salvar"*.

Para desinstalar: `.\uninstall.ps1`.

## Compilar do fonte

Requisitos: Windows, Navisworks Manage 2025 e/ou 2027 instalado (o build compila cada ano que encontrar; `-Years` escolhe) (as DLLs da API são referenciadas, nunca copiadas), .NET SDK 8+ e [uv](https://docs.astral.sh/uv/).

```powershell
.\build.ps1
```

O build:

1. cria `.venv` com as dependências travadas por hash (`scripts/requirements.lock`);
2. roda os testes do servidor;
3. gera `navis-mcp.exe` com o PyInstaller;
4. compila os dois add-ins para cada ano (2025 e 2027);
5. testa o exe;
6. monta `dist\Navis-mcp\` e `dist\Navis-mcp-1.0.0-win-x64.zip` com o sha256.

## Testes

```powershell
.venv\Scripts\python.exe tests\test_nwd_protocol.py      # nwd_* contra um plug-in falso (TCP + descritor)
.venv\Scripts\python.exe tests\smoke_stdio.py dist\Navis-mcp\server\navis-mcp\navis-mcp.exe
```

## Estrutura

```
server/naviscoord/          servidor MCP (NavisCoord) + unified.py
server/naviscoord/nwd/      port do servidor nwd-mcp (client, tools, budget, bake)
addins/NavisCoord.Addin/    add-in NavisCoord (C#, net48)
addins/nwd/                 plug-in nwd (C#, net48): shared/ + plugin-navis25/ + plugin-navis27/
scripts/                    entry do exe e lock de dependências
tests/                      testes sem Navisworks
third_party/                licenças originais
```

## Licença

O código do Navis-mcp é MIT (© 2026 Julia Nazka); veja o [LICENSE](LICENSE). O NavisCoord é MIT (© Horizun Group) e o nwd-mcp é Apache-2.0 (© Khoa Le), e as licenças deles valem para as partes que vieram de cada um. Detalhes e lista de mudanças em [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Navis-mcp não tem relação com a Autodesk. Navisworks é marca da Autodesk, Inc.
