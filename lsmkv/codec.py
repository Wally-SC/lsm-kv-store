"""Formato binário de registro, compartilhado pelo WAL e pelos arquivos SSTable.

    +---------+----------+----------+---------+-----------+
    | crc32   | tam_chave| tam_valor| chave   | valor     |
    | 4 bytes | 4 bytes  | 4 bytes  | N bytes | M bytes   |
    +---------+----------+----------+---------+-----------+

* inteiros em big-endian;
* ``crc32`` cobre tudo depois dele (tamanhos, chave e valor);
* ``tam_valor == 0xFFFFFFFF`` marca uma **lápide** (chave removida), sem bytes de valor.
"""

from __future__ import annotations

import struct
import zlib
from typing import BinaryIO, Iterator

CABECALHO = struct.Struct(">III")  # crc, tam_chave, tam_valor
LAPIDE = 0xFFFFFFFF
MAX_CHAVE = 0xFFFF  # 64 KiB - 1


class ErroDeCorrupcao(Exception):
    """Dados em disco inválidos (checksum errado, registro truncado, ordem quebrada)."""


def codificar(chave: bytes, valor: bytes | None) -> bytes:
    """Serializa um registro. ``valor=None`` representa remoção (lápide)."""
    tam_valor = LAPIDE if valor is None else len(valor)
    corpo = struct.pack(">II", len(chave), tam_valor) + chave + (valor or b"")
    return struct.pack(">I", zlib.crc32(corpo)) + corpo


def ler_registros(arquivo: BinaryIO, estrito: bool = False) -> Iterator[tuple[bytes, bytes | None, int]]:
    """Lê registros em sequência, devolvendo ``(chave, valor, offset_do_fim_do_registro)``.

    Num arquivo íntegro termina no fim limpo. Se encontrar um registro truncado ou com
    checksum inválido:

    * ``estrito=False`` (WAL): para ali em silêncio. Um registro incompleto no fim é o
      resultado normal de uma queda no meio de uma escrita.
    * ``estrito=True`` (SSTable): levanta ErroDeCorrupcao, pois esses arquivos só aparecem
      depois de gravados por completo.
    """

    def invalido(motivo: str, posicao: int):
        if estrito:
            raise ErroDeCorrupcao(f"{motivo} no offset {posicao}")

    while True:
        inicio = arquivo.tell()
        cabecalho = arquivo.read(CABECALHO.size)
        if not cabecalho:
            return
        if len(cabecalho) < CABECALHO.size:
            invalido("cabeçalho truncado", inicio)
            return

        crc, tam_chave, tam_valor = CABECALHO.unpack(cabecalho)
        if tam_chave == 0 or tam_chave > MAX_CHAVE:
            invalido("tamanho de chave inválido", inicio)
            return

        lapide = tam_valor == LAPIDE
        tam_corpo = tam_chave + (0 if lapide else tam_valor)
        corpo = arquivo.read(tam_corpo)
        if len(corpo) < tam_corpo:
            invalido("registro truncado", inicio)
            return
        if zlib.crc32(cabecalho[4:] + corpo) != crc:
            invalido("checksum inválido", inicio)
            return

        chave = corpo[:tam_chave]
        yield chave, (None if lapide else corpo[tam_chave:]), arquivo.tell()
