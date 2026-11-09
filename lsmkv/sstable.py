"""SSTable: arquivo imutável com registros ordenados por chave."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from lsmkv.codec import ErroDeCorrupcao, codificar, ler_registros


class _Ausente:
    def __repr__(self) -> str:
        return "AUSENTE"


AUSENTE = _Ausente()  # "esta SSTable não sabe nada sobre a chave" (diferente de lápide)


def escrever(caminho: str | Path, itens_ordenados: Iterable[tuple[bytes, bytes | None]]) -> None:
    """Grava uma SSTable de forma atômica: escreve num .tmp, sincroniza e só então renomeia.

    Assim nunca existe um arquivo ``.sst`` pela metade, mesmo se o processo cair no meio.
    """
    caminho = Path(caminho)
    temporario = caminho.with_name(caminho.name + ".tmp")
    anterior: bytes | None = None
    with open(temporario, "wb") as arquivo:
        for chave, valor in itens_ordenados:
            if anterior is not None and chave <= anterior:
                raise ValueError("itens precisam chegar em ordem estritamente crescente de chave")
            anterior = chave
            arquivo.write(codificar(chave, valor))
        arquivo.flush()
        os.fsync(arquivo.fileno())
    os.replace(temporario, caminho)


class SSTable:
    """Leitor de SSTable. Mantém em memória um índice ``chave -> (offset, tamanho)``.

    O índice cobre TODAS as chaves (simples, mas gasta memória); trocar por um índice
    esparso com busca binária por blocos está no ROADMAP.
    """

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)
        self._indice: dict[bytes, tuple[int, int] | None] = {}
        anterior: bytes | None = None
        with open(self.caminho, "rb") as arquivo:
            for chave, valor, fim in ler_registros(arquivo, estrito=True):
                if anterior is not None and chave <= anterior:
                    raise ErroDeCorrupcao(f"chaves fora de ordem em {self.caminho.name}")
                anterior = chave
                self._indice[chave] = None if valor is None else (fim - len(valor), len(valor))

    def __len__(self) -> int:
        return len(self._indice)

    def obter(self, chave: bytes):
        """Devolve o valor, ``None`` se a chave foi removida (lápide) ou ``AUSENTE`` se não consta."""
        if chave not in self._indice:
            return AUSENTE
        posicao = self._indice[chave]
        if posicao is None:
            return None
        offset, tamanho = posicao
        with open(self.caminho, "rb") as arquivo:
            arquivo.seek(offset)
            valor = arquivo.read(tamanho)
        if len(valor) != tamanho:
            raise ErroDeCorrupcao(f"leitura truncada em {self.caminho.name}")
        return valor
