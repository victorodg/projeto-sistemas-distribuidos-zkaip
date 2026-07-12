# zKAIP

Chat P2P em grupos, sem servidor central. Cada peer roda a mesma aplicação;
peers se conectam diretamente uns aos outros via TCP.

Requer apenas Python 3 (biblioteca padrão — nenhuma dependência externa).

## Estrutura

```
zkaip/
  main.py          ponto de entrada
  peer.py          estado central do peer (identidade, clock, tabela de conexões)
  server.py        aceita conexões TCP entrantes
  connection.py     framing TCP + uma conexão persistente (leitura/escrita/heartbeat/reconexão)
  dispatcher.py     roteia envelopes recebidos para o handler correto
  group_manager.py  grupos, membros e histórico de mensagens (não conhece sockets)
  lamport.py         relógio de Lamport
  storage.py         leitura/escrita atômica de JSON em disco
  cli.py             loop de comandos e exibição de mensagens
  models.py          dataclasses (Message, Group, MemberInfo) + montagem de envelopes
  data/               gerado automaticamente (peer.json, groups.json, messages/*.json)
  downloads/          arquivos recebidos via /send são salvos aqui
```

## Rodando duas instâncias localmente (teste)

Abra dois terminais na pasta `zkaip/`.

**Terminal A** (peer "A"):

```bash
python main.py
```

Na primeira execução ele vai perguntar a porta — digite `5001`. Isso cria
`data/peer.json` com um novo `peerId` e o histórico em `data/`.

**Terminal B** (peer "B"):

Como os dois peers rodam a partir da mesma pasta `zkaip/data/`, rode a
segunda instância a partir de uma cópia da pasta do projeto (ou defina uma
pasta de dados separada — veja "Múltiplas instâncias" abaixo). Supondo uma
cópia em `zkaip-b/`:

> ⚠️ **Faça a cópia antes de rodar o peer original pela primeira vez**, ou
> apague `zkaip-b/data/peer.json` antes de rodar. Se `zkaip-b/data/` for
> copiado depois que o peer original já rodou (e já tiver `peer.json`
> salvo), a cópia herda o mesmo `peerId` e a mesma porta — o programa
> carrega esse arquivo e não pergunta a porta de novo, achando que já é
> aquele peer. Veja "Múltiplas instâncias" abaixo.

```bash
python main.py
```

Digite `5002` quando solicitado.

### Criando um grupo e trocando mensagens

No terminal A:

```
> /create 127.0.0.1 5002
grupo criado: 3f2a9c1b (completo: 3f2a9c1b-...)
> /msg 3f2a9c1b Oi, tudo bem?
```

No terminal B você deve ver a conexão sendo estabelecida e a mensagem
chegando:

```
[info] conectado a a1b2c3d4 (127.0.0.1:5001)
[info] grupo 3f2a9c1b criado por a1b2c3d4
[14:32] a1b2c3d4 (3f2a9c1b): Oi, tudo bem?
> /msg 3f2a9c1b Tudo, e você?
```

Adicionar um terceiro peer (apenas quem criou o grupo pode fazer isso):

```
> /add 3f2a9c1b 127.0.0.1 5003
```

Ver grupos e status dos membros:

```
> /groups
```

Enviar um arquivo:

```
> /send 3f2a9c1b caminho/para/arquivo.txt
```

O peer que recebe a oferta verá uma notificação e deve responder com
`/accept <fileId>` ou `/reject <fileId>`. O arquivo aceito é salvo em
`downloads/`.

Sair:

```
> /quit
```

## Múltiplas instâncias na mesma máquina

Cada instância grava seu estado (identidade, grupos, mensagens) em
`zkaip/data/`, começando por `data/peer.json` — é esse arquivo que guarda o
`peerId` e a porta escolhidos na primeira execução. Para rodar mais de um
peer na mesma máquina, use uma cópia do diretório do projeto por peer (ex:
`zkaip-a/`, `zkaip-b/`, `zkaip-c/`), cada um escutando em uma porta
diferente (5001, 5002, 5003, ...). Todos usam `127.0.0.1` como host.

**Cuidado com a ordem**: como `data/` não faz parte do repositório Git
(está no `.gitignore`), uma cópia feita via `git clone` sempre começa sem
`peer.json` e pede a porta normalmente. Mas se você copiar a pasta
manualmente pelo sistema de arquivos (ex: "copiar e colar" no Explorer)
*depois* de já ter rodado aquele peer ao menos uma vez, o `data/peer.json`
já existente é copiado junto — e a cópia vai carregar o mesmo `peerId` e a
mesma porta salvos ali, sem perguntar nada. Para evitar isso, copie a pasta
**antes** da primeira execução, ou apague `data/peer.json` (ou a pasta
`data/` inteira) da cópia antes de rodar `python main.py` nela.

## Comandos da CLI

```
/create <host> <porta>           cria um grupo com esse peer
/add <groupId> <host> <porta>    adiciona um membro ao grupo (só o criador)
/msg <groupId> <texto>           envia uma mensagem ao grupo
/send <groupId> <caminho>        oferece um arquivo ao grupo
/groups                          lista grupos e membros (com status online/offline)
/accept <fileId>                 aceita uma oferta de arquivo pendente
/reject <fileId>                 recusa uma oferta de arquivo pendente
/leave <groupId>                 sai do grupo (extensão sobre LEAVE_GROUP)
/quit                            desconecta e encerra
```

`groupId` e `fileId` podem ser digitados por completo ou apenas os 8
primeiros caracteres (como exibidos na tela), desde que o prefixo seja
suficiente para identificar um único grupo/arquivo.

## Notas de implementação

- Framing TCP: prefixo de 4 bytes (big-endian) com o tamanho do payload
  JSON UTF-8, obrigatório pois TCP não preserva fronteiras de mensagem
  (ver `connection.py`, funções `send_msg`/`recv_msg`/`recvn`).
- Relógio de Lamport: incrementado a cada envio, atualizado
  (`max(local, recebido) + 1`) a cada recebimento — feito de forma
  centralizada em `Dispatcher.handle`.
- Heartbeat: a cada 15s por conexão; se `HEARTBEAT_ACK` não chegar em 10s,
  tenta mais 2 vezes antes de marcar a conexão como offline.
- Reconexão: backoff simples (5s, 10s, 30s, repetindo em 30s) usando o
  `host`/`port` aprendidos no handshake.
- Sincronização: ao completar (ou recompletar) um handshake, o peer envia
  automaticamente `MSG_SYNC_REQ` para cada grupo compartilhado com o peer
  remoto, usando o maior `clock` já conhecido localmente naquele grupo.
  Mensagens recuperadas são exibidas com a marca `[recuperada]`.
- "PeerName" na exibição de mensagens é o `peerId` truncado para 8
  caracteres (o protocolo não define apelidos/nicknames).
- Como `input()` não expõe o buffer sendo digitado, mensagens chegando em
  background limpam a linha atual (`\r\033[K`) e reimprimem apenas o
  prompt (`> `) — texto que o usuário já havia digitado nessa linha pode
  precisar ser redigitado. Funciona melhor em terminais com suporte a
  sequências ANSI (Windows Terminal, a maioria dos terminais Unix).
- Oferta de arquivo: em vez de bloquear a thread de rede esperando
  `input()` (o que colidiria com a thread principal da CLI lendo stdin ao
  mesmo tempo), a oferta apenas notifica o usuário; a resposta é dada via
  os comandos explícitos `/accept` e `/reject`.
