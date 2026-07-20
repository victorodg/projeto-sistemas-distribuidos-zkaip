# zKAIP

Chat P2P em grupos em que cada peer roda a mesma aplicação;
peers se conectam diretamente uns aos outros via TCP.

Requer apenas Python 3 (nenhuma dependência externa).

## Estrutura

```
zkaip/
  main.py           código principal de início
  peer.py           estado central do peer (identidade, clock, tabela de conexões)
  server.py         aceita conexões TCP entrantes
  connection.py     framing TCP + uma conexão persistente (leitura/escrita/heartbeat/reconexão)
  dispatcher.py     direciona envelopes recebidos para o handler correto
  group_manager.py  grupos, membros e histórico de mensagens (não conhece sockets)
  lamport.py        relógio de Lamport
  storage.py        leitura/escrita de JSON em disco
  cli.py            loop de comandos e exibição de mensagens
  models.py         dataclasses (Message, Group, MemberInfo) + montagem de envelopes
  data/             gerado automaticamente (peer.json, groups.json, messages/*.json)
  downloads/        arquivos recebidos via /send são salvos aqui
```

`peerId` e `groupId` são UUIDs usados apenas internamente pelo protocolo
(framing das mensagens, nomes de arquivo em `data/messages/`). Nada disso
aparece na CLI: o que o usuário vê e digita são **nomes de usuário** e
**nomes de grupo** escolhidos.

## Rodando duas instâncias localmente

Como foi projetado para a interação entre dois usuários em diferentes máquinas, 
para rodar localmente é preciso criar duas pastas diferentes e abrir um terminal
em cada. Caso a pasta `data/` seja copiada junto, é preciso excluí-la para criar
um peer com nome e porta novos. 

**Terminal A** (peer "A"):

```bash
python main.py
```

Na primeira execução ele vai perguntar a porta e o nome de usuário. 
Isso cria `data/peer.json` com um novo `peerId` interno (invisível) e o histórico em `data/`.

**Terminal B** (peer "B"):

Como os dois peers rodam a partir da mesma pasta `zkaip/data/`, rode a
segunda instância a partir de uma cópia da pasta do projeto. Supondo uma
cópia em `zkaip-b/`:

> **Importante: O ideal é fazer a cópia antes de rodar o peer original pela primeira vez**, visto que
> se `zkaip-b/data/` for copiado depois que o peer original já rodou (e já tiver `peer.json`
> salvo), a cópia herda a mesma identidade e a mesma porta, ou seja, o programa
> carrega esse arquivo e não pergunta porta/nome de novo, achando que já é
> aquele peer.

```bash
python main.py
```

### Criando um grupo e trocando mensagens

No terminal A, criando um grupo chamado `Feijoada` com o peer que está
escutando em `127.0.0.1:5002`:

```
> /create Feijoada 127.0.0.1 5002
grupo 'Feijoada' criado com Pedro
> /choose Feijoada
--- Feijoada ---
> /msg Oi, tudo bem?
[14:32] você: Oi, tudo bem?
```

No terminal B você deve ver a conexão sendo estabelecida e a mensagem
chegando:

```
[info] conectado a Victor (127.0.0.1:5001)
[info] grupo 'Feijoada' criado por Victor
> /choose Feijoada
--- Feijoada ---
[14:32] Victor: Oi, tudo bem?
> /msg Tudo, e você?
```

`/choose <grupoNome>` "abre a tela" daquele grupo: mostra as últimas mensagens
trocadas nele e, a partir daí, `/msg` e `/send` passam a valer para esse
grupo automaticamente, sem precisar informar o grupo de novo a cada
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
`zkaip/data/`, começando por `data/peer.json`. Esse arquivo guarda a
identidade interna e a porta escolhidos na primeira execução. Para rodar
mais de um peer na mesma máquina, use uma cópia do diretório do projeto por
peer (ex: `zkaip-a/`, `zkaip-b/`, `zkaip-c/`), cada um escutando em uma
porta diferente (5001, 5002, 5003, ...). Todos usam `127.0.0.1` como host.

## Comandos da CLI

```
/create <nomeGrupo> <host> <porta>   cria um grupo com esse nome, convidando o peer em host:porta
/add <nomeGrupo> <host> <porta>      adiciona um membro ao grupo (só o criador)
/choose <nomeGrupo>                  abre a tela do grupo: mostra o histórico recente e o torna o grupo atual
/msg <texto>                         envia uma mensagem ao grupo atualmente escolhido (via /choose)
/send <caminho>                      oferece um arquivo ao grupo atualmente escolhido
/groups                              lista grupos e membros (com status online/offline)
/accept <fileId>                     aceita uma oferta de arquivo pendente
/reject <fileId>                     recusa uma oferta de arquivo pendente
/leave <nomeGrupo>                   sai do grupo indicado, ou do grupo atual se omitido (extensão sobre LEAVE_GROUP)
/quit                                desconecta e encerra
```

Nomes de grupo não podem conter espaços (são digitados como um único
argumento de comando) e precisam ser únicos entre os seus próprios grupos.
Como não existe um servidor central coordenando nomes, nada impede que
*outro* peer, sem saber, crie um grupo com o mesmo nome em uma conversa
totalmente diferente. `fileId` (usado só em `/accept`/`/reject`) pode ser
digitado por completo ou só os 8 primeiros caracteres mostrados na tela.
