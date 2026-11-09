# lsm-kv-store

Banco de dados **chave-valor persistente** baseado em **LSM-tree**, escrito do zero em
Python (só biblioteca padrão), no mesmo desenho de armazenamento de bancos como
LevelDB, RocksDB e Cassandra.

> **Status: em desenvolvimento (v0.1).** O caminho de escrita, leitura e recuperação
> de falhas já funciona e é bem testado. Compactação, filtro de Bloom e varredura
> por intervalo ainda não existem. O plano está no [ROADMAP](ROADMAP.md).

## Como funciona

```
 put/delete ──► WAL (disco, append-only) ──► memtable (memória)
                                                  │ cheia?
                                                  ▼
 get ──► memtable ──► SSTable nova ──► ... ──► SSTable antiga     (a primeira que conhece a chave decide)
```

| Peça | Arquivo | Função |
|---|---|---|
| Formato de registro | `lsmkv/codec.py` | `crc32 + tamanhos + chave + valor`; lápide marca remoção |
| WAL | `lsmkv/wal.py` | grava cada escrita **antes** de aplicá-la; permite reconstruir a memtable após uma queda |
| SSTable | `lsmkv/sstable.py` | arquivo imutável ordenado por chave, gravado de forma atômica (`.tmp` + `rename`) |
| Motor | `lsmkv/engine.py` | orquestra escrita, leitura, flush e recuperação |

### Garantias e decisões

- **Durabilidade:** com `sincronizar=True` (padrão) cada escrita faz `fsync` no WAL antes de retornar.
- **Recuperação:** ao abrir, o WAL é relido. Um registro **pela metade** no fim (queda no meio
  de uma escrita) é detectado pelo checksum e **cortado**, para que as escritas seguintes
  continuem legíveis.
- **Flush seguro:** a SSTable é publicada com `rename` atômico **antes** de esvaziar o WAL.
  Uma queda entre os dois passos só reaplica dados idênticos, sem perda nem duplicação.
- **Remoções:** viram *lápides* (tombstones). Uma lápide numa SSTable nova esconde o valor de
  uma SSTable antiga, e isso persiste após reabrir o banco.
- **Corrupção:** num WAL, para no primeiro registro inválido (o que vem depois não é confiável).
  Numa SSTable, que nunca deveria estar parcial, levanta `ErroDeCorrupcao`.

## Uso

```python
from lsmkv import LSMStore

with LSMStore("meu_banco", limite_memtable=1 << 20) as db:
    db.put("usuario:1", "ana")
    print(db.get("usuario:1"))      # b'ana'
    db.delete("usuario:1")
    print(db.get("usuario:1"))      # None
    print(db.estatisticas())
```

Pela linha de comando:

```bash
python -m lsmkv meu_banco put cor azul
python -m lsmkv meu_banco get cor
python -m lsmkv meu_banco flush
python -m lsmkv meu_banco stats
```

## Testes

```bash
pip install pytest
pytest
```

A suíte (36 testes) cobre o formato binário (incluindo registros truncados e bytes
alterados), SSTables e o motor, com cenários de queda: WAL pela metade, WAL corrompido,
gravação de SSTable interrompida e queda entre flush e limpeza do WAL.
Há também um **teste contra modelo**: milhares de operações aleatórias (`put`, `delete`,
`get`, `flush` e reaberturas) aplicadas ao banco e a um `dict`, que precisam concordar sempre.
Eu verifiquei que esse teste pega bugs reais: quebrando de propósito o tratamento de
lápides, quatro testes passam a falhar.

## Limitações atuais

- Sem **compactação**: as SSTables só se acumulam e lápides nunca são descartadas.
- O índice de cada SSTable guarda **todas as chaves em memória**.
- **Não é thread-safe** (um único escritor por vez).
- Sem varredura por intervalo, sem snapshots e sem compressão.
- Não faz `fsync` do diretório após o `rename` (necessário para durabilidade total em alguns sistemas de arquivos).
