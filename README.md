# 🎙️ Transcriber

Transcrição de áudio **100% local** para macOS (Apple Silicon), com interface web.
Sem nuvem, sem API keys, sem custo por minuto — o áudio nunca sai da sua máquina.

## Features

- 📁 **Arquivos** — arraste qualquer áudio/vídeo (mp3, wav, m4a, mp4, mkv…)
- ▶️ **YouTube** — cole o link, o áudio é extraído com `yt-dlp` e transcrito
- 🔴 **Tempo real** — transcrição ao vivo do microfone via WebSocket
- 🌎 **99 idiomas** com detecção automática (Whisper large-v3-turbo)
- ⬇️ Exporta `.txt` e `.srt` (legendas com timestamps)
- ⚡ Roda no GPU via **MLX/Metal** — ~20–30x tempo real num M5

## Stack

| Componente | Uso |
|---|---|
| [mlx-whisper](https://github.com/ml-explore/mlx-examples) | Whisper `large-v3-turbo` otimizado p/ Apple Silicon |
| FastAPI + Uvicorn | Backend e WebSocket |
| yt-dlp | Extração de áudio de links do YouTube |
| ffmpeg | Conversão de formatos e decodificação do stream |

## Setup

### Pré-requisitos

- macOS com Apple Silicon (M1 ou superior)
- [Homebrew](https://brew.sh)

```bash
brew install ffmpeg yt-dlp uv
```

### Instalação

```bash
git clone https://github.com/alexandre-amaral/transcriber.git
cd transcriber

# cria o ambiente virtual e instala as dependências
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python \
  mlx-whisper fastapi "uvicorn[standard]" python-multipart websockets
```

> Sem `uv`, o clássico também funciona:
> `python3 -m venv .venv && ./.venv/bin/pip install mlx-whisper fastapi "uvicorn[standard]" python-multipart websockets`

### Rodar

```bash
npm run dev
# ou diretamente:
./.venv/bin/python server.py --port 7100
```

Abra **http://localhost:7100** no navegador.

Na primeira execução o modelo (~1,5 GB) é baixado do Hugging Face e fica em cache em `~/.cache/huggingface`. O indicador no topo da página mostra quando ele está pronto.

## Uso

### Arquivo
Arraste um arquivo para a área pontilhada, escolha o idioma (ou deixe em "Detectar automaticamente") e clique em **Transcrever**. O resultado pode ser baixado em `.txt` ou `.srt`.

### YouTube
Cole o link do vídeo e clique em **Baixar e transcrever**. Funciona com qualquer link suportado pelo `yt-dlp`.

### Tempo real
Clique em **Iniciar gravação** e fale. A transcrição aparece em janelas de ~4 segundos.

**Para gravar reuniões (sua voz + áudio dos outros participantes):**

```bash
brew install blackhole-2ch
```

Depois abra o app **Configuração de Áudio e MIDI** do macOS, crie um *dispositivo agregado* combinando seu microfone + BlackHole, e selecione esse dispositivo como entrada (nas Preferências de Som ou pelo seletor do navegador).

## Configuração

| Variável de ambiente | Default | Descrição |
|---|---|---|
| `TRANSCRIBER_MODEL` | `mlx-community/whisper-large-v3-turbo` | Modelo do Hugging Face (ex.: `mlx-community/whisper-large-v3` para máxima qualidade) |
| `PORT` / `HOST` | `7100` / `127.0.0.1` | Endereço do servidor |

## Estrutura

```
transcriber/
├── server.py            # backend FastAPI (arquivo, YouTube, WebSocket ao vivo)
├── static/index.html    # interface web (SPA, sem build)
├── package.json         # npm run dev → sobe o servidor
└── tmp/                 # arquivos temporários (limpos automaticamente)
```

## Como funciona o modo ao vivo

O navegador captura o microfone com `MediaRecorder` (webm/opus) e envia os chunks por WebSocket. O servidor acumula o stream, decodifica com ffmpeg para PCM 16 kHz e transcreve janelas de ~4 s com 0,5 s de sobreposição, removendo palavras duplicadas na junção. O modelo fica carregado em memória entre as janelas, então a latência é baixa mesmo com o modelo grande.

## Licença

MIT
