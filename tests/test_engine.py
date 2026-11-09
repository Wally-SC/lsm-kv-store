import random

import pytest

from lsmkv import ErroDeCorrupcao, LSMStore


@pytest.fixture
def pasta(tmp_path):
    return tmp_path / "db"


def abrir(pasta, **opcoes):
    opcoes.setdefault("sincronizar", False)  # fsync não é necessário para testar a lógica
    return LSMStore(pasta, **opcoes)


# --- operações básicas ---------------------------------------------------
def test_put_get_sobrescrever_e_remover(pasta):
    with abrir(pasta) as db:
        assert db.get("a") is None
        db.put("a", "1")
        assert db.get("a") == b"1"
        db.put("a", "2")
        assert db.get("a") == b"2"
        db.delete("a")
        assert db.get("a") is None


def test_str_e_bytes_sao_equivalentes(pasta):
    with abrir(pasta) as db:
        db.put("chave", b"valor")
        assert db.get(b"chave") == b"valor"
        db.put(b"\x00\xff", b"\x01\x02")
        assert db.get(b"\x00\xff") == b"\x01\x02"


def test_valor_vazio_existe(pasta):
    with abrir(pasta) as db:
        db.put("k", "")
        assert db.get("k") == b""  # vazio é diferente de ausente


def test_validacoes(pasta):
    with abrir(pasta) as db:
        with pytest.raises(ValueError):
            db.put("", "x")
        with pytest.raises(ValueError):
            db.get("")
        with pytest.raises(ValueError):
            db.put(b"k" * 70000, "x")
    with pytest.raises(ValueError):
        LSMStore(pasta, limite_memtable=0)


def test_usar_depois_de_fechar_falha(pasta):
    db = abrir(pasta)
    db.fechar()
    with pytest.raises(RuntimeError):
        db.put("a", "1")
    with pytest.raises(RuntimeError):
        db.get("a")


# --- durabilidade --------------------------------------------------------
def test_dados_sobrevivem_a_reabertura_so_pelo_wal(pasta):
    with abrir(pasta) as db:
        db.put("a", "1")
        db.put("b", "2")
        db.delete("a")
        assert db.estatisticas()["sstables"] == 0
    with abrir(pasta) as db:
        assert db.get("a") is None
        assert db.get("b") == b"2"


def test_flush_automatico_cria_sstables(pasta):
    with abrir(pasta, limite_memtable=200) as db:
        for i in range(50):
            db.put(f"chave-{i:03d}", "x" * 20)
        estat = db.estatisticas()
        assert estat["sstables"] >= 2
        assert estat["bytes_memtable"] < 200
        for i in range(50):
            assert db.get(f"chave-{i:03d}") == b"x" * 20


def test_tudo_sobrevive_a_reabertura_com_sstables(pasta):
    with abrir(pasta, limite_memtable=200) as db:
        for i in range(50):
            db.put(f"chave-{i:03d}", f"valor-{i}")
    with abrir(pasta, limite_memtable=200) as db:
        assert db.estatisticas()["sstables"] >= 2
        assert [db.get(f"chave-{i:03d}") for i in range(50)] == [f"valor-{i}".encode() for i in range(50)]


def test_valor_mais_novo_vence_entre_sstables(pasta):
    with abrir(pasta) as db:
        db.put("k", "velho")
        db.flush()
        db.put("k", "novo")
        db.flush()
        assert db.estatisticas()["sstables"] == 2
        assert db.get("k") == b"novo"
    with abrir(pasta) as db:
        assert db.get("k") == b"novo"


def test_lapide_esconde_valor_de_sstable_mais_antiga(pasta):
    with abrir(pasta) as db:
        db.put("k", "v")
        db.flush()
        db.delete("k")
        assert db.get("k") is None  # lápide na memtable
        db.flush()
        assert db.get("k") is None  # lápide numa SSTable mais nova
    with abrir(pasta) as db:
        assert db.get("k") is None
        db.put("k", "de-volta")
        assert db.get("k") == b"de-volta"


def test_flush_sem_dados_nao_cria_arquivo(pasta):
    with abrir(pasta) as db:
        db.flush()
        assert db.estatisticas()["sstables"] == 0


# --- recuperação de falhas -----------------------------------------------
def test_queda_sem_fechar_recupera_pelo_wal(pasta):
    db = abrir(pasta)
    db.put("a", "1")
    db.put("b", "2")
    # sem db.fechar(): simula o processo morrendo
    with abrir(pasta) as recuperado:
        assert recuperado.get("a") == b"1"
        assert recuperado.get("b") == b"2"


def test_wal_com_registro_pela_metade_e_cortado(pasta):
    with abrir(pasta) as db:
        db.put("a", "1")
        db.put("b", "2")
    wal = pasta / "wal.log"
    tamanho_bom = wal.stat().st_size
    with open(wal, "ab") as f:
        f.write(b"\x12\x34\x56\x78\x00\x00\x00\x05\x00\x00")  # cabeçalho incompleto: queda no meio da escrita

    with abrir(pasta) as db:
        assert db.get("a") == b"1" and db.get("b") == b"2"
        assert wal.stat().st_size == tamanho_bom  # lixo removido
        db.put("c", "3")  # escrita depois da recuperação precisa continuar legível
    with abrir(pasta) as db:
        assert db.get("c") == b"3"


def test_wal_corrompido_no_meio_preserva_so_o_que_vem_antes(pasta):
    with abrir(pasta) as db:
        db.put("a", "1")
        db.put("b", "2")
        db.put("c", "3")
    wal = pasta / "wal.log"
    dados = bytearray(wal.read_bytes())
    dados[len(dados) // 2 + 3] ^= 0xFF  # estraga o registro do meio
    wal.write_bytes(bytes(dados))

    with abrir(pasta) as db:
        assert db.get("a") == b"1"
        assert db.get("b") is None and db.get("c") is None  # comportamento documentado


def test_queda_durante_gravacao_de_sstable_e_ignorada(pasta):
    with abrir(pasta) as db:
        db.put("a", "1")
        db.flush()
    (pasta / "sst-000009.sst.tmp").write_bytes(b"gravacao interrompida")
    with abrir(pasta) as db:
        assert db.get("a") == b"1"
        assert db.estatisticas()["sstables"] == 1
    assert not (pasta / "sst-000009.sst.tmp").exists()


def test_queda_entre_gravar_sstable_e_limpar_wal_nao_perde_nem_duplica(pasta):
    with abrir(pasta) as db:
        db.put("a", "1")
        db.put("b", "2")
        wal_antes = (pasta / "wal.log").read_bytes()
        db.flush()
    # simula a queda: a SSTable existe, mas o WAL antigo ainda estava lá
    (pasta / "wal.log").write_bytes(wal_antes)
    with abrir(pasta) as db:
        assert db.get("a") == b"1" and db.get("b") == b"2"


def test_sstable_corrompida_impede_abertura(pasta):
    with abrir(pasta) as db:
        db.put("a", "valor")
        db.flush()
    arquivo = next(pasta.glob("sst-*.sst"))
    dados = bytearray(arquivo.read_bytes())
    dados[-1] ^= 0xFF
    arquivo.write_bytes(bytes(dados))
    with pytest.raises(ErroDeCorrupcao):
        abrir(pasta)


# --- teste contra um modelo ----------------------------------------------
@pytest.mark.parametrize("semente", [1, 2, 3])
def test_comportamento_igual_a_um_dict_com_reaberturas(pasta, semente):
    """Operações aleatórias aplicadas ao banco e a um dict; os dois têm de concordar sempre."""
    rng = random.Random(semente)
    modelo: dict[bytes, bytes] = {}
    chaves = [f"k{i:02d}".encode() for i in range(30)]
    db = abrir(pasta, limite_memtable=150)
    try:
        for passo in range(1500):
            operacao = rng.choices(["put", "delete", "get", "reabrir", "flush"], weights=[50, 20, 25, 3, 2])[0]
            chave = rng.choice(chaves)
            if operacao == "put":
                valor = f"v{passo}".encode()
                db.put(chave, valor)
                modelo[chave] = valor
            elif operacao == "delete":
                db.delete(chave)
                modelo.pop(chave, None)
            elif operacao == "get":
                assert db.get(chave) == modelo.get(chave), f"passo {passo}, chave {chave!r}"
            elif operacao == "flush":
                db.flush()
            else:
                db.fechar()
                db = abrir(pasta, limite_memtable=150)

        for chave in chaves:
            assert db.get(chave) == modelo.get(chave)
    finally:
        db.fechar()
