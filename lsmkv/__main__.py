"""CLI mínima para brincar com o banco: python -m lsmkv <diretorio> put|get|del|flush|stats ..."""

from __future__ import annotations

import argparse
import sys

from lsmkv.engine import LSMStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lsmkv")
    parser.add_argument("diretorio")
    sub = parser.add_subparsers(dest="comando", required=True)
    put = sub.add_parser("put")
    put.add_argument("chave")
    put.add_argument("valor")
    sub.add_parser("get").add_argument("chave")
    sub.add_parser("del").add_argument("chave")
    sub.add_parser("flush")
    sub.add_parser("stats")
    args = parser.parse_args(argv)

    with LSMStore(args.diretorio) as banco:
        if args.comando == "put":
            banco.put(args.chave, args.valor)
        elif args.comando == "get":
            valor = banco.get(args.chave)
            if valor is None:
                print("(nao encontrado)", file=sys.stderr)
                return 1
            print(valor.decode("utf-8", errors="replace"))
        elif args.comando == "del":
            banco.delete(args.chave)
        elif args.comando == "flush":
            banco.flush()
        elif args.comando == "stats":
            for nome, valor in banco.estatisticas().items():
                print(f"{nome}: {valor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
