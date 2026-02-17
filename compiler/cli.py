import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="nifc")
    parser.add_argument("command", choices=["lex", "parse", "check", "codegen"], help="Compiler phase command")
    parser.add_argument("input", help="Input source file")
    args = parser.parse_args()

    print(f"TODO: implement '{args.command}' for {args.input}")
    return 0
