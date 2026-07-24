#!/usr/bin/env python3

import os
import sqlite3


ROOT = "/storage/emulated/0/QPX_ALPHA"


def find_sqlite_files():

    found=[]

    for root, dirs, files in os.walk(ROOT):

        for f in files:

            if f.endswith(
                (".db", ".sqlite", ".sqlite3")
            ):

                found.append(
                    os.path.join(root,f)
                )

    return found



def inspect_database(path):

    print("\nDATABASE:")
    print(path)

    try:

        conn = sqlite3.connect(path)

        cur = conn.cursor()

        cur.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
            """
        )

        tables = [
            x[0]
            for x in cur.fetchall()
        ]

        conn.close()


        print(
            "Tables:"
        )

        for t in tables:
            print(
                " -",
                t
            )


        return True


    except Exception as e:

        print(
            "ERROR:",
            e
        )

        return False



def inspect_python_database_references():

    print(
        "\nSearching Python references..."
    )

    keywords=[
        ".db",
        "sqlite",
        "connect("
    ]


    for root, dirs, files in os.walk(ROOT):

        for f in files:

            if f.endswith(".py"):

                path=os.path.join(
                    root,
                    f
                )

                try:

                    text=open(
                        path,
                        encoding="utf-8"
                    ).read()

                    for k in keywords:

                        if k in text:

                            print(
                                "[REF]",
                                path
                            )

                            break


                except:
                    pass



def main():

    print(
        "QPX DATABASE LOCATOR"
    )


    dbs=find_sqlite_files()


    if not dbs:

        print(
            "\nNo physical SQLite files found."
        )


    else:

        for db in dbs:

            inspect_database(db)



    inspect_python_database_references()



if __name__=="__main__":
    main()