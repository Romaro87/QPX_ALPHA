import os
import ast

ROOT = "/storage/emulated/0/QPX_ALPHA"

print("="*50)
print("QPX MODULE INVENTORY")
print("="*50)

for root, dirs, files in os.walk(ROOT):

    for file in files:

        if file.endswith(".py"):

            path = os.path.join(root,file)

            print("\nFILE:")
            print(path)

            try:

                with open(path,"r",encoding="utf-8") as f:
                    tree = ast.parse(f.read())

                for node in tree.body:

                    if isinstance(node, ast.ClassDef):

                        print(
                            " CLASS:",
                            node.name
                        )

                    if isinstance(node, ast.FunctionDef):

                        print(
                            " FUNCTION:",
                            node.name
                        )

            except Exception as e:

                print(
                    " ERROR:",
                    e
                )


print("\nInventory Complete")