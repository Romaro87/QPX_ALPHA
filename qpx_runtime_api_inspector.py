#!/usr/bin/env python3

import os
import inspect
import importlib


ROOT = "/storage/emulated/0/QPX_ALPHA"


MODULES = [
    "feature_engine",
    "signal_engine",
    "backtesting_engine"
]


def inspect_module(name):

    print("\n=================================")
    print("MODULE:", name)
    print("=================================")

    try:

        module = importlib.import_module(name)

        print("\nClasses:")

        for obj_name, obj in inspect.getmembers(module):

            if inspect.isclass(obj):

                print(
                    "\nCLASS:",
                    obj_name
                )

                print(
                    "Constructor:"
                )

                try:
                    print(
                        inspect.signature(obj)
                    )
                except:
                    pass


                print(
                    "Methods:"
                )

                for method_name, method in inspect.getmembers(
                    obj,
                    predicate=inspect.isfunction
                ):

                    if not method_name.startswith("_"):

                        try:

                            print(
                                " -",
                                method_name,
                                inspect.signature(method)
                            )

                        except:

                            print(
                                " -",
                                method_name
                            )


    except Exception as e:

        print(
            "IMPORT ERROR:",
            e
        )


def main():

    print(
        "QPX RUNTIME API INSPECTOR"
    )


    for module in MODULES:

        inspect_module(module)



if __name__ == "__main__":
    main()