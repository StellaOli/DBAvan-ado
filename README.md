# 🎵 Cypher Music - Sistema de Recomendação Musical
<p align="center">
  <img src="https://github.com/StellaOli/DBAvan-ado/blob/main/20180703190744-rollsafe-meme.jpeg?raw=true" alt="Cypher Logo" width="300">
</p>

## 🚀 Visão Geral

O Cypher Music é um sistema inteligente de recomendação musical que combina tecnologias modernas para criar uma experiência personalizada de descoberta de músicas. O projeto utiliza:

- **FastAPI** para a API principal
- **Kafka** para processamento de eventos em tempo real
- **CockroachDB** (PostgreSQL) para dados de usuários
- **MongoDB** para dados de músicas
- **Redis** para cache
- **Elasticsearch** para logging e monitoramento

## ✨ Funcionalidades Principais

- 🎧 Sistema de recomendação baseado em preferências do usuário
- 🔍 Integração com a API do Spotify para busca de músicas
- 📊 Dashboard de monitoramento em tempo real
- 🔄 Processamento assíncrono de eventos com Kafka
- 📈 Análise de logs e métricas de desempenho

## 🛠️ Pré-requisitos

Antes de começar, você precisará ter instalado:

- Python 3.8+
- pip (gerenciador de pacotes Python)

## ⚙️ Configuração do Ambiente

1. **Baixe o DBase.zip e faça a descompactação do arquivo**:
   ```bash
   git clone https://github.com/StellaOli/DBAvan-ado.git
   ```
2. **Instale as dependências**:
   ```bash
   pip install -r requirements.txt
   ```


## 🏃 Executando o Projeto

1. **Inicie o servidor principal**:
   ```bash
   python main.py
   ```

2. **Acesse a aplicação**:
   Abra seu navegador **EM GUIA ANÔNIMA** [http://localhost:8001](http://localhost:8001)

3. **Serviços adicionais**:
   - API: roda na porta 8000
   - Consumer: processa mensagens do Kafka
   - Monitor: coleta métricas e gera alertas

## 📚 Guia de Uso

1. **Cadastro de Usuários**:
   - Acesse `/users/create` para criar um novo perfil
   - Defina seus gêneros musicais preferidos

2. **Busca de Músicas**:
   - Use `/spotify/search` para encontrar músicas na plataforma Spotify
   - Adicione músicas à sua biblioteca

3. **Recomendações**:
   - Solicite recomendações baseadas em suas preferências
   - O sistema analisa seu histórico e sugere novas músicas

4. **Monitoramento**:
   - Acesse `/monitor` para ver o status dos serviços
   - Verifique métricas de desempenho e logs

## 🎥 Vídeo Explicativo

Assista ao nosso tutorial completo no YouTube:

[![Vídeo Explicativo](https://img.youtube.com/vi/O7-fIpWpSi0/0.jpg)](https://www.youtube.com/watch?v=O7-fIpWpSi0)

## 📦 Estrutura do Projeto

```
cypher-music/
├── main.py            # Aplicação FastAPI principal
├── s1_api.py          # Serviço de API
├── s2_consumer.py     # Consumidor Kafka
├── s3_monitor.py      # Serviço de monitoramento
├── connections.py     # Conexões com bancos de dados
├── static/            # Arquivos estáticos (CSS, JS)
├── templates/         # Templates HTML
├── requirements.txt   # Dependências do projeto
└── README.md          # Este arquivo
```

## ✉️ Alunos

Luís Marim - 22.224.018-6
Stella Oli - 22.125.082-2
---

Feito com ❤️ e Python! 🐍
