"""Write-Ahead Log: toda escrita é anotada aqui ANTES de entrar na memória.

Se o processo cair, o conteúdo da memtable é reconstruído relendo este arquivo.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from lsmkv.codec import codificar, ler_registros


class WAL:
    def __init__(self, caminho: str | Path, sincronizar: bool = True) -> None:
        self.caminho = Path(caminho)
        self._sincronizar = sincronizar
        self._arquivo: BinaryIO = open(self.caminho, "ab")

    @staticmethod
    def recuperar(caminho: str | Path) -> list[tuple[bytes, bytes | None]]:
        """Lê os registros válidos e **corta** qualquer lixo no final do arquivo.

        O corte é necessário: se um registro pela metade ficasse no arquivo, tudo o que
        fosse anexado depois dele ficaria ilegível na próxima recuperação.
        """
        caminho = Path(caminho)
        if not caminho.exists():
            return []
        registros: list[tuple[bytes, bytes | None]] = []
        fim_valido = 0
        with open(caminho, "rb") as arquivo:
            for chave, valor, fim in ler_registros(arquivo, estrito=False):
                registros.append((chave, valor))
                fim_valido = fim
        if caminho.stat().st_size > fim_valido:
            with open(caminho, "r+b") as arquivo:
                arquivo.truncate(fim_valido)
        return registros

    def anexar(self, chave: bytes, valor: bytes | None) -> None:
        self._arquivo.write(codificar(chave, valor))
        self._arquivo.flush()
        if self._sincronizar:
            os.fsync(self._arquivo.fileno())  # só depois disso a escrita é durável

    def reiniciar(self) -> None:
        """Esvazia o log (usado depois que a memtable virou SSTable)."""
        self._arquivo.close()
        self._arquivo = open(self.caminho, "wb")
        self._arquivo.close()
        self._arquivo = open(self.caminho, "ab")

    def fechar(self) -> None:
        if not self._arquivo.closed:
            self._arquivo.close()
