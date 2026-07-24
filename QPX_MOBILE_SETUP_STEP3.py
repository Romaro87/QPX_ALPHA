import os


print("==============================")
print(" QPX Alpha v0.8 Mobile Setup ")
print(" Step 3 - CSV Import Setup")
print("==============================")


# Create sample CSV file

csv_content = """date,open,high,low,close,volume
2026-01-01,100,105,98,103,150000
2026-01-02,103,108,102,107,180000
2026-01-03,107,109,104,106,170000
"""


with open("sample_market.csv", "w") as file:
    file.write(csv_content)


print("[OK] Created sample_market.csv")


# Create mobile importer if missing

mobile_folder = os.path.join(
    "quant_platform",
    "mobile"
)


if not os.path.exists(mobile_folder):
    os.makedirs(mobile_folder)


init_file = os.path.join(
    mobile_folder,
    "__init__.py"
)


if not os.path.exists(init_file):
    open(init_file, "w").close()


print("[OK] Mobile package verified")


# Add importer connection helper

runner_file = "mobile_runner.py"


if os.path.exists(runner_file):

    with open(runner_file, "r") as file:
        runner = file.read()


    connection_code = """

from quant_platform.mobile import csv_importer

print("[OK] Mobile CSV importer connected")

csv_importer.import_market_csv(
    "sample_market.csv"
)

"""


    if "import_market_csv" not in runner:

        with open(runner_file, "a") as file:
            file.write(connection_code)


        print("[OK] Updated mobile_runner.py")


    else:
        print("[OK] mobile_runner.py already connected")


else:
    print("[WARNING] mobile_runner.py not found")


print("")
print("QPX Alpha Step 3 Setup Complete")
print("==============================")
