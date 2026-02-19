import argparse


PHASE_COMMANDS = ["lex", "parse", "check", "codegen"]


def main() -> int:
    parser = argparse.ArgumentParser(prog="nifc")
    parser.add_argument("command", choices=PHASE_COMMANDS, help="Compiler phase command")
    parser.add_argument("input", help="Input source file")
    args = parser.parse_args()

    print(f"Command '{args.command}' is not implemented yet (input: {args.input}).")
    return 0
