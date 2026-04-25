# Smart GPS

Plataforma de simulacao logistica para ambiente portuario, com foco em rastreamento operacional, roteirizacao em grafo real, supervisao em mapa e experiencia dedicada para condutor.

O projeto foi construido para demonstrar uma operacao terrestre mais proxima da realidade: ativos distribuidos por zonas operacionais, fluxos coerentes, gargalos naturais, monitoramento visual e selecao de veiculos com suporte a ML.

## Visao geral

O Smart GPS combina:

- simulacao operacional em porto com zonas reais de trabalho
- malha viaria baseada em OpenStreetMap
- dashboard unica com autenticacao e perfis `Supervisor` e `Condutor`
- animacao de ativos sobre a geometria da rota
- motor de eventos com congestionamentos, bloqueios e hotspots
- dataset sintetico para treinamento e comparacao entre heuristica e IA

## Principais funcionalidades

### Operacao e simulacao

- zonas operacionais como `gate`, `rail`, `yard`, `warehouse`, `pier`, `maintenance` e `crossroads`
- fluxos recorrentes como `rail -> yard -> pier`, `gate -> warehouse -> pier` e patrulha de manutencao
- frota heterogenea com caminhões, utilitarios, apoio, pickups, guindastes e trens
- trens restritos a corredores ferroviarios dedicados
- pontos criticos que elevam risco, congestionamento e chance de evento

### Dashboard

- autenticacao mockada com sessao persistida
- modo `Supervisor` com mapa principal, filtros, ativos, alertas, detalhes e metricas
- modo `Condutor` com instrucao principal, ETA, velocidade, destino e mapa simplificado
- troca de estrategia entre `Regra deterministica` e `IA / ML` no supervisor
- foco em um ativo no mapa e controle visual para reduzir poluicao

### Roteirizacao e movimento

- roteamento em `NetworkX` sobre grafo com geometria real
- movimento animado sobre a polyline da rota
- heading visual para ativos rodoviarios
- progresso monotônico na rota, evitando recuos visuais espurios
- velocidade dinamica por tipo de veiculo, via, congestionamento, criticidade, densidade e contexto operacional

### ML e dados sinteticos

- geracao de cenarios sinteticos para decisao de despacho
- treinamento de classificador e regressor
- comparacao entre selecao heuristica e selecao orientada por modelo
- fallback automatico para regra quando o modelo nao estiver carregado

## Stack

- Backend: FastAPI
- Frontend: HTML, CSS e JavaScript puro
- Mapa: Leaflet + OpenStreetMap
- Roteirizacao: NetworkX
- ML: scikit-learn
- Dados: pandas + numpy
- Geoespacial: OSMnx + Shapely

## Arquitetura

```text
app/
  api/           # endpoints REST
  core/          # configuracao da aplicacao
  data/          # datasets e seeds locais
  ml/            # features e inferencia do modelo
  routing/       # carga do grafo e roteamento
  simulation/    # motor principal da simulacao
  static/        # frontend da dashboard
  templates/     # HTML base
scripts/
  refresh_osm_graph.py
  train_model.py
tests/
README.md
requirements.txt
```

## Como executar

### 1. Criar ambiente virtual

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Rodar a aplicacao

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8010
```

Abra no navegador:

- [http://127.0.0.1:8010](http://127.0.0.1:8010)

## Credenciais de demonstracao

- `condutor@demo.com` / `demo123`
- `supervisor@demo.com` / `demo123`

## Perfis de acesso

### Supervisor

- acompanha a operacao completa no mapa
- filtra ativos por tipo e status
- abre detalhe por ativo
- alterna entre regra heuristica e estrategia baseada em ML
- acompanha bloqueios, congestionamento, hotspots e metricas operacionais

### Condutor

- recebe instrucao de navegacao em destaque
- visualiza velocidade, destino, status e ETA
- acompanha alertas relevantes de rota
- alterna entre veiculos disponiveis no proprio dashboard

## Regras de velocidade operacional

O simulador nao usa mais uma velocidade fixa baixa por ativo. A velocidade-alvo varia com base em:

- tipo do veiculo
- limite da via
- tipo de via
- zona operacional atual
- congestionamento
- bloqueios
- densidade local
- criticidade da aresta
- tipo de fluxo
- proposito da rota
- aproximacao de manobra e de destino

As transicoes sao suavizadas para que a velocidade logica, a velocidade exibida e a velocidade percebida no mapa fiquem coerentes.

## Roteamento e fidelidade geografica

- a malha viaria e carregada a partir do OpenStreetMap
- o grafo preserva direcao, arestas paralelas e geometria valida
- setores operacionais sao snapados para a malha real
- corredores ferroviarios sinteticos dedicados complementam a operacao dos trens
- o simulador evita criar conectores falsos para vias inexistentes

## Endpoints principais

### Dashboard e autenticacao

- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `GET /api/dashboard/driver`
- `GET /api/dashboard/supervisor`
- `GET /api/assets/{asset_id}`

### Controle da simulacao

- `GET /api/state`
- `POST /api/start`
- `POST /api/pause`
- `POST /api/reset`
- `POST /api/step?steps=1`
- `POST /api/runtime`
- `POST /api/strategy`

### Dados e avaliacao

- `POST /api/events`
- `POST /api/requests`
- `POST /api/synthetic`
- `POST /api/scenario`
- `POST /api/compare`
- `GET /api/export/csv`
- `GET /api/export/json`

## Treinamento do modelo

Para treinar os modelos com o dataset sintetico:

```powershell
python scripts/train_model.py app/data/sample_synthetic_dataset.csv
```

Os artefatos gerados sao carregados automaticamente quando presentes em `app/data/models/`.

## Testes

```powershell
pytest
```

Cobertura atual inclui:

- roteamento
- bloqueio e recalculo de rota
- dataset sintetico
- selecao de veiculos

## Roadmap

- ingestao de dados privados complementares do porto
- historico persistido em banco
- replay temporal de operacao
- calibracao operacional com SLAs reais
- ampliacao do uso de ML para ETA e previsao de gargalos
