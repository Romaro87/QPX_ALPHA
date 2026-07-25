import sys

USAGE = '''
Usage:

python -m tools.scaffold module ModuleName

python -m tools.scaffold service ServiceName

python -m tools.scaffold adr "Title"

(Implementation coming in Sprint 4)
'''

def main():
    print("=" * 50)
    print("QPX_ALPHA Scaffold Tool")
    print("=" * 50)
    print()

    if len(sys.argv) < 2:
        print(USAGE)
        return

    print("Scaffolding support will be implemented during Sprint 4.")
    print()
    print("Arguments:", sys.argv[1:])

if __name__ == "__main__":
    main()
