import os


def setup_mobile_folder():

    print("==============================")
    print(" QPX Alpha Mobile Setup ")
    print("==============================")


    mobile_folder = os.path.join(
        "quant_platform",
        "mobile"
    )


    # Create folder
    if not os.path.exists(mobile_folder):
        os.makedirs(mobile_folder)
        print("[OK] Created mobile folder")
    else:
        print("[OK] Mobile folder already exists")


    # Create csv importer test file
    importer_file = os.path.join(
        mobile_folder,
        "csv_importer.py"
    )


    if not os.path.exists(importer_file):

        with open(importer_file, "w") as file:

            file.write(
'''print("CSV Importer loaded")
'''
            )

        print("[OK] Created csv_importer.py")

    else:
        print("[OK] csv_importer.py already exists")


    print()
    print("Mobile setup complete")
    print()


if __name__ == "__main__":
    setup_mobile_folder()
