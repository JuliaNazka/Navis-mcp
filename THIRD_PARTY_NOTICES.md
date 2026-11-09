# Third-party notices

Navis-mcp junta dois projetos open-source num único servidor MCP. Cada um continua sob a própria licença.

## Qual licença vale para cada parte

| Parte | Licença |
|---|---|
| Código escrito para o Navis-mcp: `server/naviscoord/unified.py`, o port em `server/naviscoord/nwd/`, `addins/NavisCoord.Addin/ClashCompat.cs`, scripts de build/instalação/teste e documentação | MIT, © 2026 Julia Nazka ([`LICENSE`](LICENSE)) |
| NavisCoord: `server/naviscoord/` (menos `nwd/` e `unified.py`), `addins/NavisCoord.Addin/`, `profiles/` | MIT, © 2026 Horizun Group |
| nwd-mcp: `addins/nwd/` e o código do servidor portado para `server/naviscoord/nwd/` | Apache-2.0, © 2026 Khoa Le |

O `LICENSE` da raiz não substitui as licenças originais, que valem para as partes que vieram de cada projeto.

## NavisCoord — MIT

- Origem: https://github.com/HorizunGroup/naviscoord-mcp, tag `v1.1.2` (commit `2f3681b`)
- Copyright (c) 2026 Horizun Group
- Licença: MIT, texto completo em [`third_party/naviscoord/LICENSE`](third_party/naviscoord/LICENSE); aviso em [`third_party/naviscoord/NOTICE`](third_party/naviscoord/NOTICE)
- Onde está aqui: `server/naviscoord/` (menos `nwd/` e `unified.py`), `addins/NavisCoord.Addin/`, `profiles/`, `scripts/frozen_entry.py`, `scripts/requirements.lock`
- O que mudou:
  - `server/naviscoord/mcp_server.py`: o servidor se apresenta como `navis-mcp` com a versão do Navis-mcp, e `main()` chama `unified.configure()` antes de rodar. As ferramentas `navis_*` não mudaram.
  - **Port para o Navisworks 2027** (o NavisCoord oficial suporta 2024–2026): no 2027 a Autodesk passou a organizar os testes de clash em pastas. `DocumentClashTests.Tests` saiu, e `TestsAddCopy`/`TestsRemove` passaram a receber a pasta-mãe. O arquivo novo `addins/NavisCoord.Addin/ClashCompat.cs` concentra essa API: no 2027 ele percorre `Value.TestsRoot` e as subpastas, e nas versões antigas usa a lista plana. Os 31 pontos que usavam `TestsData.Tests`, `TestsAddCopy` e `TestsRemove` passaram a chamar o `ClashCompat`. O `.csproj` ganhou `NavisworksYear` (padrão 2027) e a constante `NAVIS2027`.
  - **Distribuição como bundle**: o add-in vai em `%APPDATA%\Autodesk\ApplicationPlugins\NavisCoord.bundle`, com um componente por ano, e não mais em `%APPDATA%\Autodesk\Navisworks Manage <ano>\Plugins\NavisCoord`. Em teste ao vivo, o Navisworks 2027 não carregou o add-in a partir da pasta `Plugins` e carregou a partir do bundle.
  - **Colorir e limpar cores** (`bridge.py`, `mcp_server.py`): no NavisCoord 1.1.2, inclusive no `main` em 08/11/2026, o servidor não enviava `expected_document_fingerprint` para `appearance/color` e `appearance/reset`, e mandava um reset vazio. O add-in recusa as duas coisas, então colorir e limpar nunca chegavam ao modelo. Agora a "huella" vai junto, `navis_color_by_priority` devolve os `appearance_operation_ids`, e `navis_reset_appearance` desfaz exatamente esses coloreados (ou o id informado), sem apagar cores postas à mão.
  - **Perfil OG7** (`server/naviscoord/profiles/og7.json`, gerado por `scripts/make_og7_profile.py` a partir do `default.json`): códigos do OG7 e conjuntos/pares no formato do add-in.
  - Testes, scripts de release e plugins de marketplace do NavisCoord não foram copiados.

## nwd-mcp — Apache License 2.0

- Origem: https://github.com/bimwright/nwd-mcp, tag `v1.0.0` (commit `370c35f`)
- Copyright 2026 Khoa Le
- Licença: Apache 2.0, texto completo em [`third_party/nwd-mcp/LICENSE`](third_party/nwd-mcp/LICENSE). O projeto não traz arquivo NOTICE.
- Onde está aqui:
  - `addins/nwd/shared/` e `addins/nwd/plugin-navis25/`: código e projeto 2025 do plug-in, sem alterações.
  - `addins/nwd/plugin-navis27/`: projeto do plug-in para o Navisworks 2027. O `plugin-navis27` da v1.0.0 não compilava: referenciava uma `Autodesk.Navisworks.Api.Controls.dll` que não existe e não tinha o pacote `IsExternalInit`. Este projeto foi refeito a partir do `plugin-navis25`, mudando só o ano, a constante e a pasta da API.
  - `server/naviscoord/nwd/`: **trabalho derivado**. O servidor .NET 8 (`src/server/`) foi reescrito em Python para rodar no mesmo processo do NavisCoord.
- O que mudou (Apache 2.0, seção 4(b)):
  - `PluginClient.cs` e `TargetRegistry.cs` viraram `client.py`. O protocolo com o plug-in é o mesmo: descritor JSON, TCP loopback, um envelope NDJSON por conexão.
  - `NwdMcpConfig.cs` e `ToolsetFilter.cs` viraram `config.py`. O modo leitura deixou de ser lido de `BIMWRIGHT_NWD_READ_ONLY` e segue a chave única do Navis-mcp (ligada por padrão).
  - `ResponseBudget.cs`, `ResponseSizePolicy.cs`, `ResponseSpillWriter.cs` e `MutationResponseCompactor.cs` viraram `budget.py`, com os mesmos limites (64/256 KiB, 1 MiB), os mesmos formatos de spill (json, ndjson, sqlite, text) e as mesmas pastas.
  - `Bake/*.cs`, `Handlers/*.cs` e os auxiliares de ToolBaker/Security usados pelo servidor viraram `bake.py`, com o mesmo `bake.db`. A validação do registro e o mascaramento de segredos ficaram simplificados.
  - `Tools/*.cs` viraram `tools.py`. Nomes, parâmetros, padrões, descrições (`descriptions.py`, copiadas literalmente) e anotações são os mesmos.
  - `ReleaseUpdateCheck` e o log de chamadas do servidor não foram portados.
- `build.ps1` gera um `PackageContents.xml` com um componente por ano: 2025 (série `Nw22`) e 2027 (série `Nw24`).

## Autodesk

Navis-mcp não tem relação com a Autodesk, Inc. Autodesk e Navisworks são marcas da Autodesk, Inc. Os add-ins são compilados contra a API .NET de uma instalação local do Navisworks Manage 2027, e nenhum assembly da Autodesk é redistribuído: as referências usam `Private=false`.

## Dependências Python empacotadas no `navis-mcp.exe`

O build instala as versões travadas em `scripts/requirements.lock` (por hash) e as empacota com o PyInstaller. As principais:

| Pacote | Licença |
|---|---|
| mcp | MIT |
| pydantic / pydantic-core | MIT |
| anyio, httpx, starlette, uvicorn | MIT / BSD-3-Clause |
| reportlab | BSD-3-Clause |
| Pillow | MIT-CMU |
| PyInstaller (bootloader) | GPL-2.0 com exceção para bootloader, que permite distribuir executáveis gerados |

Cada pacote é distribuído pelos próprios autores sob a própria licença. O texto oficial está nos metadados de cada um.

Os plug-ins nwd também incluem Newtonsoft.Json (MIT) e Microsoft.CodeAnalysis / Roslyn (MIT), restaurados do NuGet no build.
