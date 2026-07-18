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

`peerId` e `groupId` são UUIDs usados apenas internamente pelo protocolo
(framing das mensagens, nomes de arquivo em `data/messages/`). Nada disso
aparece na CLI: o que o usuário vê e digita são **nomes de usuário** e
**nomes de grupo** escolhidos por vocês.

## Rodando duas instâncias localmente (teste)

Abra dois terminais na pasta `zkaip/`.

**Terminal A** (peer "A"):

```bash
python main.py
```

Na primeira execução ele vai perguntar a porta e o nome de usuário — digite
`5001` e, por exemplo, `Alice`. Isso cria `data/peer.json` com um novo
`peerId` interno (invisível) e o histórico em `data/`.

**Terminal B** (peer "B"):

Como os dois peers rodam a partir da mesma pasta `zkaip/data/`, rode a
segunda instância a partir de uma cópia da pasta do projeto (ou defina uma
pasta de dados separada — veja "Múltiplas instâncias" abaixo). Supondo uma
cópia em `zkaip-b/`:

> ⚠️ **Faça a cópia antes de rodar o peer original pela primeira vez**, ou
> apague `zkaip-b/data/peer.json` antes de rodar. Se `zkaip-b/data/` for
> copiado depois que o peer original já rodou (e já tiver `peer.json`
> salvo), a cópia herda a mesma identidade e a mesma porta — o programa
> carrega esse arquivo e não pergunta porta/nome de novo, achando que já é
> aquele peer. Veja "Múltiplas instâncias" abaixo.

```bash
python main.py
```

Digite `5002` e um nome de usuário (ex: `Bob`) quando solicitado.

### Criando um grupo e trocando mensagens

No terminal A, criando um grupo chamado `Feijoada` com o peer que está
escutando em `127.0.0.1:5002`:

```
> /create Feijoada 127.0.0.1 5002
grupo 'Feijoada' criado com Bob
> /choose Feijoada
--- Feijoada ---
> /msg Oi, tudo bem?
[14:32] você: Oi, tudo bem?
```

No terminal B você deve ver a conexão sendo estabelecida e a mensagem
chegando:

```
[info] conectado a Alice (127.0.0.1:5001)
[info] grupo 'Feijoada' criado por Alice
> /choose Feijoada
--- Feijoada ---
[14:32] Alice: Oi, tudo bem?
> /msg Tudo, e você?
```

`/choose <nome>` "abre a tela" daquele grupo: mostra as últimas mensagens
trocadas nele e, a partir daí, `/msg` e `/send` passam a valer para esse
grupo automaticamente — sem precisar informar o grupo de novo a cada
comando. Mensagens de **outros** grupos (que não o escolhido no momento)
continuam aparecendo, mas marcadas com `(nome do grupo)` para não se
confundirem com a conversa atual.

Adicionar um terceiro peer (apenas quem criou o grupo pode fazer isso):

```
> /add Feijoada 127.0.0.1 5003
```

Ver grupos e status dos membros:

```
> /groups
```

Enviar um arquivo para o grupo atualmente escolhido:

```
> /send caminho/para/arquivo.txt
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
`zkaip/data/`, começando por `data/peer.json` — é esse arquivo que guarda a
identidade interna e a porta escolhidos na primeira execução. Para rodar
mais de um peer na mesma máquina, use uma cópia do diretório do projeto por
peer (ex: `zkaip-a/`, `zkaip-b/`, `zkaip-c/`), cada um escutando em uma
porta diferente (5001, 5002, 5003, ...). Todos usam `127.0.0.1` como host.

**Cuidado com a ordem**: como `data/` não faz parte do repositório Git
(está no `.gitignore`), uma cópia feita via `git clone` sempre começa sem
`peer.json` e pede porta/nome normalmente. Mas se você copiar a pasta
manualmente pelo sistema de arquivos (ex: "copiar e colar" no Explorer)
*depois* de já ter rodado aquele peer ao menos uma vez, o `data/peer.json`
já existente é copiado junto — e a cópia vai carregar a mesma identidade e
a mesma porta salvas ali, sem perguntar nada. Para evitar isso, copie a
pasta **antes** da primeira execução, ou apague `data/peer.json` (ou a
pasta `data/` inteira) da cópia antes de rodar `python main.py` nela.

## Comandos da CLI

```
/create <nome> <host> <porta>    cria um grupo com esse nome, convidando o peer em host:porta
/add <nome> <host> <porta>       adiciona um membro ao grupo (só o criador)
/choose <nome>                   "abre a tela" do grupo: mostra o histórico recente e o torna o grupo atual
/msg <texto>                     envia uma mensagem ao grupo atualmente escolhido (via /choose)
/send <caminho>                  oferece um arquivo ao grupo atualmente escolhido
/groups                          lista grupos e membros (com status online/offline)
/accept <fileId>                 aceita uma oferta de arquivo pendente
/reject <fileId>                 recusa uma oferta de arquivo pendente
/leave [nome]                    sai do grupo indicado, ou do grupo atual se omitido (extensão sobre LEAVE_GROUP)
/quit                             desconecta e encerra
```

Nomes de grupo não podem conter espaços (são digitados como um único
argumento de comando) e precisam ser únicos entre os seus próprios grupos —
mas como não existe um servidor central coordenando nomes, nada impede que
*outro* peer, sem saber, crie um grupo com o mesmo nome em uma conversa
totalmente diferente. `fileId` (usado só em `/accept`/`/reject`) pode ser
digitado por completo ou só os 8 primeiros caracteres mostrados na tela.

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
- Identidade e nomes: `peerId`/`groupId` (UUIDs) são estritamente internos
  — usados no protocolo e no nome dos arquivos em `data/messages/`, nunca
  exibidos na CLI. `HANDSHAKE`, `CREATE_GROUP` e `ADD_MEMBER` carregam um
  campo extra `username`/`groupName` (extensão sobre o payload descrito na
  especificação original) para que cada peer saiba como exibir os outros.
  `Peer.display_name(peerId)` resolve esse nome mesmo para membros
  offline, a partir do cache preenchido pelo handshake e pela lista de
  membros dos grupos.
- Como `input()` não expõe o buffer sendo digitado, mensagens chegando em
  background limpam a linha atual (`\r\033[K`) e reimprimem apenas o
  prompt — texto que o usuário já havia digitado nessa linha pode precisar
  ser redigitado. Funciona melhor em terminais com suporte a sequências
  ANSI (Windows Terminal, a maioria dos terminais Unix).
- Oferta de arquivo: em vez de bloquear a thread de rede esperando
  `input()` (o que colidiria com a thread principal da CLI lendo stdin ao
  mesmo tempo), a oferta apenas notifica o usuário; a resposta é dada via
  os comandos explícitos `/accept` e `/reject`.

### Bugs corrigidos depois da primeira versão

- **Timeout "fantasma" no socket, causando reconexões em loop.**
  `socket.create_connection((host, port), timeout=5)` (usado para o
  *connect*) deixa esse timeout de 5s permanentemente aplicado ao socket
  retornado. Sem resetá-lo, qualquer período de silêncio maior que 5s (o
  normal em um chat parado) fazia `recv()` estourar timeout, o que o
  código tratava como conexão perdida — desconectando, reconectando (com
  o mesmo problema) e gerando exatamente o padrão relatado de
  `"conectado"`/`"ficou offline"` se repetindo sem parar. Corrigido com
  `sock.settimeout(None)` logo após conectar (`peer.py`, `connect_to`).
  Esse era o principal responsável pelo comportamento reportado ao testar
  localmente.
- **Corrida de conexão duplicada.** Como cada peer tenta se reconectar
  proativamente a todo membro conhecido de um grupo, é possível os dois
  lados discarem um para o outro quase ao mesmo tempo, abrindo duas
  conexões TCP para o mesmo par de peers. Antes, cada lado decidia sozinho
  qual conexão manter com base na ordem local de chegada dos handshakes —
  o que podia divergir entre os dois lados e gerar um ciclo permanente de
  fechar/reconectar. Agora a decisão é determinística: os dois peers
  conhecem os dois `peerId`s após o handshake e ambos preferem,
  independentemente, a conexão discada pelo `peerId` menor — convergindo
  sempre para a mesma conexão sobrevivente nos dois lados, sem depender de
  timing (`peer.py`, `register_connection`/`_is_preferred_dialer`).
  Reiniciar os dois peers no exato mesmo instante ainda pode gerar uma
  reconexão extra nos primeiros segundos enquanto essa corrida se resolve,
  mas ela se estabiliza sozinha (não repete indefinidamente como antes).
- **Novo membro nunca recebia o grupo.** Ao ser adicionado via `/add`, o
  novo peer recebia `ADD_MEMBER`, mas o handler chamava `set_members`, que
  não faz nada se o grupo ainda não existe localmente — ou seja, quem
  acabava de entrar nunca criava o grupo de fato. Corrigido: se o grupo é
  desconhecido, ele é criado a partir da lista completa de membros
  recebida (`dispatcher.py`, `_handle_add_member`).
