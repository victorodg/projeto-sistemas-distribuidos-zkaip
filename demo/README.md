# Demonstração automática do zKAIP

Esta pasta contém uma demonstração que roda sozinha, pensada para ser
gravada como o vídeo da disciplina. Ela reaproveita o código real do
projeto (`Peer`, `CLI`, `PeerServer`) — não é uma versão fake ou
simplificada — só substitui a digitação manual por um roteiro pré-escrito,
"digitado" na tela com uma pequena animação, para dar tempo de leitura.

## Como rodar

1. Abra um PowerShell dentro desta pasta (`zkaip\demo`).
2. Rode `.\run_demo.ps1` (veja `Set-ExecutionPolicy -Scope Process
   -ExecutionPolicy Bypass` se o Windows bloquear o script).
3. Comece a gravar a tela **antes** de rodar o comando, ou logo em
   seguida — três janelas de terminal vão abrir sozinhas e a demonstração
   roda automaticamente, sem precisar tocar em nada.
4. A demonstração inteira leva alguns minutos. Ao final, as três janelas
   continuam abertas para você revisar antes de fechar.

## O que a demonstração mostra, e por quê

A demonstração usa dois peers, **Alice** (porta 6001) e **Bob** (porta
6002), e cobre os pontos que o professor pediu no vídeo: funcionalidade
geral, evidência do modelo de consistência, e comportamento diante de uma
falha tolerável.

**Janela 1 — Alice** (fica aberta do início ao fim)
Cria o grupo `Feijoada` convidando o Bob, entra na tela do grupo com
`/choose`, troca mensagens e envia um arquivo — mostrando o funcionamento
básico do chat em grupo P2P.

**Janela 2 — Bob (antes da falha)**
Recebe o convite, entra no grupo, responde e aceita o arquivo enviado pela
Alice. Depois, o próprio roteiro **encerra o processo do Bob
abruptamente** (sem desconexão graciosa), simulando uma queda real —
igual a um crash, energia caindo, ou o processo travando.

Nesse momento, observe na **janela da Alice**: o zKAIP detecta a queda
sozinho (usando o mecanismo de heartbeat) e mostra `Bob ficou offline`,
sem qualquer ação manual. Alice continua mandando mensagens normalmente —
elas ficam guardadas no histórico local dela, mesmo sem o Bob estar
alcançável.

**Janela 3 — Bob (depois, reconectando)**
Uma nova instância do Bob sobe, com a mesma identidade e a mesma porta de
antes. Ao conectar de novo com a Alice, o zKAIP sincroniza sozinho as
mensagens que foram trocadas enquanto ele estava offline (protocolo
`MSG_SYNC_REQ`/`MSG_SYNC_RES`, baseado no relógio de Lamport de cada
grupo) — essas mensagens aparecem marcadas com `[recuperada]`. Isso é a
evidência de que o modelo de consistência foi implementado corretamente:
nenhuma mensagem se perde por causa de uma falha temporária, e a ordem é
preservada.

No fim, `/groups` na janela da Alice mostra o Bob de volta como `online`,
fechando o ciclo: falha → detecção automática → o sistema continua
funcionando → reconexão → recuperação do que foi perdido.

## Ajustando a demonstração

Os arquivos `script_alice.txt`, `script_bob_before.txt` e
`script_bob_after.txt` são simples arquivos de texto, um comando por
linha — dá para editar as mensagens ou os tempos de pausa sem tocar em
nenhum `.py`. As diretivas especiais usadas neles:

```
#note: <texto>       mostra um destaque/narração na tela (com pausa embutida)
#pause:<segundos>     pausa extra, para dar mais tempo de leitura
#wait_group:<nome>    espera até o grupo existir (sincroniza com o outro peer)
#wait_offer            espera até chegar uma oferta de arquivo
#wait_online:<nome>    espera até aquele peer estar online de novo
#accept_last           aceita a oferta de arquivo mais recente
#signal:<nome>         avisa o script PowerShell que é hora de abrir a próxima janela
#crash                 encerra o processo na hora, simulando uma queda
```

As esperas (`#wait_*`) checam o estado real dos peers em vez de usar um
tempo fixo — por isso a demonstração não desincroniza mesmo que você deixe
tudo mais lento ou mais rápido editando os `#pause`.

Se quiser ver o roteiro completo do que cada peer faz, é só abrir os três
arquivos `.txt` — eles são a "atuação" linha por linha.
