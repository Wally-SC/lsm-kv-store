# Roadmap

Ordem pensada para que cada etapa seja testável sozinha e deixe o banco mais próximo de algo real.

## Concluído (v0.1)

- [x] Formato de registro com checksum e lápides
- [x] WAL com `fsync` e recuperação que corta registro incompleto
- [x] SSTables imutáveis com gravação atômica
- [x] Motor: `put`, `get`, `delete`, `flush` automático e manual, recuperação na abertura
- [x] Testes de falha e teste contra modelo (`dict`)

## Próximos passos

1. **Varredura por intervalo (`scan(inicio, fim)`)**
   Mesclar memtable e SSTables em ordem de chave com um *k-way merge* (`heapq.merge`),
   respeitando que o dado mais novo vence e lápides escondem o antigo.
2. **Compactação (compaction)**
   Mesclar SSTables em uma só, mantendo só a versão mais nova de cada chave e descartando
   lápides quando for seguro. Primeiro *size-tiered*; depois avaliar *leveled*.
   Teste-chave: o resultado de `get`/`scan` não muda antes e depois de compactar.
3. **Índice esparso nas SSTables**
   Organizar o arquivo em blocos, guardar um índice de uma chave por bloco (com rodapé que
   aponta para ele) e usar busca binária, em vez de manter todas as chaves na memória.
4. **Filtro de Bloom por SSTable**
   Evitar leituras de disco para chaves que certamente não estão na tabela.
5. **Concorrência**
   Trava de leitura/escrita ou flush em thread de fundo, com memtable imutável enquanto grava.
6. **Benchmarks**
   Escrita sequencial/aleatória e leitura, antes e depois de cada otimização, para que as
   melhorias sejam medidas e não supostas.
7. **Robustez**
   `fsync` do diretório, arquivo `MANIFEST` listando as SSTables válidas, trava de processo
   para impedir dois processos no mesmo diretório.
8. **Opcional:** compressão de blocos e API de lote (`WriteBatch`) atômica.
