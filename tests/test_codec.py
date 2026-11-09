import io
import random

import pytest

from lsmkv.codec import ErroDeCorrupcao, codificar, ler_registros


def ler(dados: bytes, estrito=False):
    return list(ler_registros(io.BytesIO(dados), estrito=estrito))


def test_ida_e_volta_com_valor_e_lapide():
    dados = codificar(b"a", b"1") + codificar(b"b", None) + codificar(b"c", b"")
    registros = ler(dados)
    assert [(k, v) for k, v, _ in registros] == [(b"a", b"1"), (b"b", None), (b"c", b"")]
    assert registros[-1][2] == len(dados)  # offset final bate com o tamanho


def test_valor_vazio_e_diferente_de_lapide():
    (_, vazio, _), = ler(codificar(b"k", b""))
    (_, lapide, _), = ler(codificar(b"k", None))
    assert vazio == b"" and lapide is None


def test_ida_e_volta_aleatoria():
    rng = random.Random(123)
    esperado = [
        (bytes(rng.randrange(256) for _ in range(rng.randrange(1, 40))),
         None if rng.random() < 0.2 else bytes(rng.randrange(256) for _ in range(rng.randrange(0, 200))))
        for _ in range(300)
    ]
    dados = b"".join(codificar(k, v) for k, v in esperado)
    assert [(k, v) for k, v, _ in ler(dados, estrito=True)] == esperado


@pytest.mark.parametrize("corte", [1, 5, 11, 13, 20])
def test_final_truncado_modo_tolerante_para_no_ultimo_registro_bom(corte):
    bom = codificar(b"a", b"1")
    quebrado = codificar(b"b", b"valor-comprido")[:corte]
    assert [(k, v) for k, v, _ in ler(bom + quebrado)] == [(b"a", b"1")]


def test_final_truncado_modo_estrito_levanta_erro():
    with pytest.raises(ErroDeCorrupcao):
        ler(codificar(b"a", b"1") + codificar(b"b", b"2")[:-1], estrito=True)


def test_checksum_detecta_byte_alterado():
    dados = bytearray(codificar(b"chave", b"valor"))
    dados[-1] ^= 0xFF
    assert ler(bytes(dados)) == []
    with pytest.raises(ErroDeCorrupcao, match="checksum"):
        ler(bytes(dados), estrito=True)


def test_cabecalho_absurdo_e_rejeitado_sem_ler_gigabytes():
    # tamanho de chave 0xFFFFFFFF: acima do limite, então nem tenta ler o corpo
    cabecalho_absurdo = b"\x00\x00\x00\x00" + (0xFFFFFFFF).to_bytes(4, "big") + (0).to_bytes(4, "big")
    assert ler(cabecalho_absurdo) == []
    with pytest.raises(ErroDeCorrupcao, match="tamanho de chave"):
        ler(cabecalho_absurdo, estrito=True)
