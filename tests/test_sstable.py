import pytest

from lsmkv.codec import ErroDeCorrupcao, codificar
from lsmkv.sstable import AUSENTE, SSTable, escrever


def test_escrever_e_ler(tmp_path):
    caminho = tmp_path / "t.sst"
    escrever(caminho, [(b"a", b"1"), (b"b", None), (b"c", b"333")])
    tabela = SSTable(caminho)
    assert len(tabela) == 3
    assert tabela.obter(b"a") == b"1"
    assert tabela.obter(b"b") is None  # lápide
    assert tabela.obter(b"c") == b"333"
    assert tabela.obter(b"zzz") is AUSENTE  # desconhecida: diferente de lápide


def test_escrita_nao_deixa_temporario(tmp_path):
    escrever(tmp_path / "t.sst", [(b"a", b"1")])
    assert [p.name for p in tmp_path.iterdir()] == ["t.sst"]


def test_exige_ordem_estritamente_crescente(tmp_path):
    with pytest.raises(ValueError):
        escrever(tmp_path / "t.sst", [(b"b", b"1"), (b"a", b"2")])
    with pytest.raises(ValueError):
        escrever(tmp_path / "t2.sst", [(b"a", b"1"), (b"a", b"2")])


def test_falha_na_escrita_nao_publica_arquivo(tmp_path):
    with pytest.raises(ValueError):
        escrever(tmp_path / "t.sst", [(b"b", b"1"), (b"a", b"2")])
    assert not (tmp_path / "t.sst").exists()


def test_leitura_detecta_arquivo_fora_de_ordem(tmp_path):
    caminho = tmp_path / "ruim.sst"
    caminho.write_bytes(codificar(b"b", b"1") + codificar(b"a", b"2"))
    with pytest.raises(ErroDeCorrupcao, match="fora de ordem"):
        SSTable(caminho)
