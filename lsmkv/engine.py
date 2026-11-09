from __future__ import annotations

import re
from pathlib import Path

from lsmkv import sstable
from lsmkv.codec import LAPIDE, MAX_CHAVE
from lsmkv.sstable import AUSENTE, SSTable
from lsmkv.wal import WAL

_PADRAO_SST = re.compile(r"^sst-(\d{6})\.sst$")
_SOBRECARGA_REGISTRO = 12  # cabeçalho de cada registro, só para estimar o tamanho da memtable


def _bytes(valor: str | bytes) -> bytes:
    return valor.encode("utf-8") if isinstance(valor, str) else bytes(valor)


class LSMStore:
    """Banco chave-valor persistente baseado em uma árvore LSM (versão inicial).

    Escrita:  WAL (disco) -> memtable (memória) -> quando cheia, vira uma SSTable imutável.
    Leitura:  memtable, depois SSTables da mais nova para a mais antiga; a primeira que
              conhecer a chave decide (inclusive se for uma lápide de remoção).
    Recuperação: ao abrir, carrega as SSTables e reaplica o WAL na memtable.

    Ainda NÃO tem: compactação, filtro de Bloom, varredura por intervalo, concorrência.
    Veja ROADMAP.md.
    """

    def __init__(self, diretorio: str | Path, limite_memtable: int = 1 << 20, sincronizar: bool = True) -> None:
        if limite_memtable < 1:
            raise ValueError("limite_memtable deve ser >= 1")
        self.diretorio = Path(diretorio)
        self.diretorio.mkdir(parents=True, exist_ok=True)
        self._limite = limite_memtable
        self._fechado = False

        self._remover_temporarios()
        self._sstables: list[tuple[int, SSTable]] = []  # (número, tabela), da mais antiga p/ mais nova
        for numero, caminho in self._listar_sstables():
            self._sstables.append((numero, SSTable(caminho)))
        self._proximo_numero = (self._sstables[-1][0] + 1) if self._sstables else 1

        self._memtable: dict[bytes, bytes | None] = {}
        self._bytes_memtable = 0
        caminho_wal = self.diretorio / "wal.log"
        for chave, valor in WAL.recuperar(caminho_wal):
            self._aplicar(chave, valor)
        self._wal = WAL(caminho_wal, sincronizar=sincronizar)

    # --- API pública --------------------------------------------------
    def put(self, chave: str | bytes, valor: str | bytes) -> None:
        chave, valor = self._validar_chave(chave), _bytes(valor)
        if len(valor) >= LAPIDE:
            raise ValueError("valor grande demais")
        self._escrever(chave, valor)

    def delete(self, chave: str | bytes) -> None:
        self._escrever(self._validar_chave(chave), None)

    def get(self, chave: str | bytes) -> bytes | None:
        self._exigir_aberto()
        chave = self._validar_chave(chave)
        if chave in self._memtable:
            return self._memtable[chave]  # None se foi removida
        for _, tabela in reversed(self._sstables):
            encontrado = tabela.obter(chave)
            if encontrado is not AUSENTE:
                return encontrado  # valor ou None (lápide); não olha tabelas mais antigas
        return None

    def flush(self) -> None:
        """Transforma a memtable numa nova SSTable e esvazia o WAL."""
        self._exigir_aberto()
        if not self._memtable:
            return
        numero = self._proximo_numero
        caminho = self.diretorio / f"sst-{numero:06d}.sst"
        sstable.escrever(caminho, sorted(self._memtable.items()))
        # Ordem importa: a SSTable já está no disco (rename atômico) antes de apagar o WAL.
        # Se cair entre os dois passos, o WAL reaplica os mesmos dados na abertura: sem perda.
        self._sstables.append((numero, SSTable(caminho)))
        self._proximo_numero += 1
        self._memtable.clear()
        self._bytes_memtable = 0
        self._wal.reiniciar()

    def estatisticas(self) -> dict[str, int]:
        return {
            "entradas_memtable": len(self._memtable),
            "bytes_memtable": self._bytes_memtable,
            "sstables": len(self._sstables),
            "chaves_em_sstables": sum(len(t) for _, t in self._sstables),
        }

    def fechar(self) -> None:
        if not self._fechado:
            self._wal.fechar()
            self._fechado = True

    def __enter__(self) -> "LSMStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.fechar()

    # --- internos -----------------------------------------------------
    def _exigir_aberto(self) -> None:
        if self._fechado:
            raise RuntimeError("o banco está fechado")

    @staticmethod
    def _validar_chave(chave: str | bytes) -> bytes:
        chave = _bytes(chave)
        if not chave:
            raise ValueError("a chave não pode ser vazia")
        if len(chave) > MAX_CHAVE:
            raise ValueError(f"chave maior que {MAX_CHAVE} bytes")
        return chave

    def _escrever(self, chave: bytes, valor: bytes | None) -> None:
        self._exigir_aberto()
        self._wal.anexar(chave, valor)  # primeiro o log...
        self._aplicar(chave, valor)  # ...depois a memória
        if self._bytes_memtable >= self._limite:
            self.flush()

    def _aplicar(self, chave: bytes, valor: bytes | None) -> None:
        if chave in self._memtable:
            self._bytes_memtable -= self._tamanho(chave, self._memtable[chave])
        self._memtable[chave] = valor
        self._bytes_memtable += self._tamanho(chave, valor)

    @staticmethod
    def _tamanho(chave: bytes, valor: bytes | None) -> int:
        return _SOBRECARGA_REGISTRO + len(chave) + (len(valor) if valor else 0)

    def _listar_sstables(self) -> list[tuple[int, Path]]:
        encontrados = []
        for caminho in self.diretorio.iterdir():
            correspondencia = _PADRAO_SST.match(caminho.name)
            if correspondencia:
                encontrados.append((int(correspondencia.group(1)), caminho))
        return sorted(encontrados)

    def _remover_temporarios(self) -> None:
        # sobra de uma queda durante a gravação de uma SSTable: nunca foi publicada, pode sumir
        for caminho in self.diretorio.glob("sst-*.sst.tmp"):
            caminho.unlink()
