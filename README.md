# Simulador Web do Porto de Ponta da Madeira

MVP funcional de um simulador logistico para operacao terrestre do Porto de Ponta da Madeira, com backend em FastAPI, visualizacao em Leaflet, roteirizacao em grafo via NetworkX, geracao de dados sinteticos e selecao de veiculos com scikit-learn.

## Correcao de fidelidade geografica

O grafo inicial do projeto era manual e aproximado, o que gerava tres problemas visuais e operacionais:

- segmentos desenhados como linhas retas entre pontos arbitrarios
- conexoes artificiais sem correspondencia com via real
- rotas aparentando cruzar agua ou sair do eixo das ruas

Isso foi refatorado. Agora o simulador:

- baixa e cacheia a rede viaria real do OpenStreetMap com `osmnx`
- preserva somente arestas vindas do OSM com geometria real
- preserva direcao, sentido de circulacao e arestas paralelas usando `MultiDiGraph`
- descarta segmentos sem geometria valida ou sem `highway` dirigivel aceito
- desenha grafo e rotas com a geometria real das vias
- posiciona pontos operacionais por snap em aresta/no valido
- expoe um modo debug para visualizar nos, snaps e arestas descartadas

## O que o projeto entrega

- mapa web navegavel com base em coordenadas reais da regiao do porto
- grafo viario real baseado em OSM com bloqueios, congestionamento e geometria de via
- simulacao em ticks com veiculos, equipes, demandas e eventos dinamicos
- calculo de rotas com custo customizado e recalculo orientado por eventos
- geracao de dataset sintetico em CSV e JSON
- treinamento de modelos de classificacao e regressao
- comparacao entre decisao por regra e decisao por modelo
- configuracao dinamica da quantidade de veiculos e equipes
- testes basicos de rota, bloqueio, dataset e selecao

## Zonas e fluxos operacionais implementados

O simulador agora usa zonas operacionais ancoradas na malha viaria real do grafo:

- `gate`: gate principal e pulmao de entrada
- `crossroads`: cruzamentos viarios criticos
- `rail`: chegada ferroviaria e travessia
- `yard`: patio de minerio
- `warehouse`: armazens internos
- `pier`: acesso aos bercos e area de embarque
- `maintenance`: manutencao e estacionamento

Cada zona:

- possui nos associados do grafo real
- influencia spawn de veiculos e equipes
- participa da geracao de demanda
- altera congestionamento e risco operacional nas arestas proximas

Fluxos recorrentes implementados:

- `rail_yard_pier`: ferrovia -> patio -> pier -> patio
- `gate_warehouse_pier`: gate -> armazens -> pier -> gate
- `maintenance_patrol`: manutencao -> patio -> cruzamentos -> manutencao

Esses fluxos alimentam:

- distribuicao espacial de entidades
- gargalos naturais nos pontos criticos
- roteamento com contexto operacional
- dataset sintetico com features de zona, fluxo e densidade

## Regras de velocidade operacional

A velocidade dos ativos nao e mais fixa por veiculo. O motor agora calcula uma velocidade-alvo dinamica ao longo da rota considerando:

- tipo do veiculo, com perfis base diferentes para trem, caminhao, pickup, apoio, utilitario e guindaste
- tipo de via, com teto operacional por `road_type`
- zona operacional da aresta, com reducao em `gate`, `crossroads`, `yard`, `pier` e `maintenance`
- congestionamento e bloqueios ativos
- densidade de veiculos na zona atual
- criticidade da aresta
- tipo de fluxo e proposito da rota
- aproximacao de manobra e aproximacao do destino

Tambem foi adicionada suavizacao entre a velocidade atual e a velocidade-alvo para evitar variacao brusca e deixar a animacao mais natural.

## Stack

- Backend: FastAPI
- Frontend: HTML, CSS e JavaScript puro
- Mapa: Leaflet + tiles OpenStreetMap
- Roteirizacao: NetworkX
- Dados sinteticos: pandas + numpy
- ML: scikit-learn
- Geoespacial: OSMnx + Shapely

## Como executar

### 1. Instalar dependencias

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Rodar a aplicacao

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Abra no navegador:

- [http://127.0.0.1:8010](http://127.0.0.1:8010)

## Dashboard unica com autenticacao

O projeto agora sobe uma unica dashboard web com dois perfis:

- `Condutor`: foco em navegacao, ETA, destino, alertas e mini mapa
- `Supervisor`: foco em mapa operacional, ativos, filtros, alertas e metricas

Usuarios demo:

- `condutor@demo.com` / `demo123`
- `supervisor@demo.com` / `demo123`

Fluxo de acesso:

1. abra a aplicacao no navegador
2. faca login com um dos usuarios demo
3. o sistema redireciona para a tela correta conforme o perfil
4. a sessao fica persistida localmente no navegador
5. use `Logout` para encerrar a sessao

Endpoints novos para a dashboard:

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/dashboard/driver`
- `GET /api/dashboard/supervisor`
- `GET /api/assets/{asset_id}`

Se quiser mudar depois sem editar codigo:

```bash
$env:APP_PORT=8020
uvicorn app.main:app --reload --host 127.0.0.1 --port $env:APP_PORT
```

### 3. Atualizar o cache OSM quando quiser refazer a malha

```bash
python scripts/refresh_osm_graph.py
```

## Como usar a interface

- `Iniciar`: comeca a evolucao automatica da simulacao
- `Pausar`: interrompe os ticks automaticos
- `Avancar 1 tick`: executa um passo manual
- `Resetar`: recria o cenario inicial
- `Gerar Demanda`: cria uma solicitacao manual de equipe
- `Criar Bloqueio`: bloqueia um trecho aleatorio ativo
- `Velocidade`: ajusta o multiplicador temporal
- `Estrategia`: alterna entre regra deterministica e ML
- `Veiculos` e `Equipes`: redefinem o volume do cenario e recriam a frota e a distribuicao das equipes
- `Comparar ML vs Regra`: executa um benchmark dos dois metodos no mesmo estado inicial
- o benchmark agora roda multiplos cenarios independentes e aponta o vencedor por tempo medio de resposta
- `Modo debug`: mostra nos do grafo, pontos snapados e arestas descartadas
- `Gerar cenarios`: adiciona centenas de exemplos sinteticos
- `Exportar CSV/JSON`: baixa o dataset acumulado

## Treinar o modelo de ML

Primeiro gere ou exporte um dataset sintetico. Depois rode:

```bash
python scripts/train_model.py app/data/sample_synthetic_dataset.csv
```

O modelo treinado sera salvo em:

- `app/data/models/vehicle_selector.joblib`
- `app/data/models/travel_time_regressor.joblib`

Depois reinicie a aplicacao para que o modelo seja carregado automaticamente.

### Como o ML funciona hoje

- a classificacao continua prevendo se um veiculo tende a ser o melhor candidato
- a regressao estima `observed_response_time_s`
- na inferencia, quando o regressor existe, a estrategia `ml` escolhe o veiculo com menor tempo previsto
- o label do dataset nao e mais a regra heuristica; ele e definido pelo menor tempo observado entre os candidatos do mesmo atendimento

## Estrutura do projeto

```text
app/
  api/
  core/
  data/
  ml/
  routing/
  simulation/
  static/
  templates/
scripts/
tests/
README.md
requirements.txt
```

## Fidelidade cartografica e origem dos dados

### Referencia geografica usada

- Latitude aproximada: `-2.565`
- Longitude aproximada: `-44.370`

### Como os dados foram obtidos

- O centro do mapa foi fixado nas coordenadas fornecidas.
- A interface usa tiles publicos do OpenStreetMap para visualizacao de fundo.
- A rede viaria principal e de servico e baixada via `osmnx` com `network_type="drive_service"` e cacheada localmente em `app/data/osm/`.
- O grafo final do simulador e reconstruido apenas com arestas reais do OSM que tenham geometria valida e `highway` compativel com trafego terrestre.
- Pontos operacionais sao snapados para a malha real; quando um seed legado cai longe demais da rede valida, o sistema deriva um ponto operacional plausivel diretamente do proprio grafo.

### O que e real

- a referencia geografica central do porto
- a visualizacao cartografica de fundo via OpenStreetMap
- o tracado das vias dirigiveis importadas do OpenStreetMap para a area consultada
- a geometria desenhada das rotas e do grafo base

### O que foi aproximado

- a escolha semantica dos pontos operacionais nomeados, quando o OSM nao traz explicitamente o nome interno do setor
- a posicao exata de alguns pontos nomeados do porto, quando os seeds antigos nao coincidiam com a malha viaria real e precisaram ser derivados do proprio grafo
- parametros operacionais como capacidade, velocidade e congestionamento por via

### Limitacoes

- A qualidade final depende da cobertura do OpenStreetMap para a area privada do porto.
- Alguns acessos internos podem nao estar completamente mapeados ou podem ter classificacao inconsistente no OSM.
- Para evitar rotas falsas, o simulador nao cria conectores sinteticos entre pontos soltos; se uma via nao existe no OSM carregado, ela nao entra no roteamento.
- Em areas onde o OSM nao nomeia setores operacionais internos, os pontos de operacao sao aproximados por nos reais da malha viaria.
- Uma evolucao futura pode adicionar ingestao complementar de GeoJSON interno, validacao topologica mais forte e reconciliacao com dados privados do porto.

## Arquitetura resumida

- `app/simulation/engine.py`: motor principal da simulacao, ticks, eventos, configuracao de volume e comparacao entre estrategias
- `app/routing/graph_loader.py`: download/cache OSM, filtragem de vias, preservacao de direcao, snap e derivacao de pontos operacionais
- `app/routing/router.py`: calculo de custo e melhor rota usando geometria real, direcao da via e velocidade do veiculo
- `app/api/routes.py`: endpoints REST da simulacao
- `app/static/app.js`: renderizacao do mapa, camadas debug, comparativo e desenho fiel das rotas
- `app/ml/features.py`: schema das features sinteticas
- `app/ml/model_service.py`: inferencia do modelo treinado
- `scripts/train_model.py`: treinamento do classificador
- `scripts/refresh_osm_graph.py`: refresh manual do cache geoespacial

## API principal

- `GET /api/state`
- `POST /api/start`
- `POST /api/pause`
- `POST /api/reset`
- `POST /api/step?steps=1`
- `POST /api/events`
- `POST /api/requests`
- `POST /api/synthetic`
- `POST /api/scenario`
- `POST /api/compare`
- `POST /api/debug`
- `GET /api/export/csv`
- `GET /api/export/json`

## Testes

```bash
pytest
```

Cobertura minima incluida:

- calculo de rota
- mudanca de rota por bloqueio
- geracao de dataset sintetico
- selecao de veiculo
- configuracao de quantidade de entidades
- comparacao entre estrategias

## Alteracoes recentes de realismo operacional

- o grafo passou a preservar direcao e arestas paralelas do OSM
- o ETA e o movimento agora dependem da velocidade do proprio veiculo
- o dataset sintetico passou a usar o menor tempo observado como label de melhor veiculo
- o benchmark passou a rodar multiplos cenarios independentes
- a estrategia `ml` prioriza regressao de tempo de resposta quando o modelo existe

## Proximos passos recomendados

- ingestao real de vias internas a partir de OSM/GeoJSON privado
- animacao mais continua por aresta e replay temporal
- regressao adicional para ETA
- persistencia historica em banco de dados
- calibracao com SLAs e tipos reais de ocorrencia
