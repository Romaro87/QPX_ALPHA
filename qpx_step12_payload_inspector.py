#!/usr/bin/env python3

import os
import sqlite3
import pprint


ROOT = "/storage/emulated/0/QPX_ALPHA"

DB = os.path.join(
    ROOT,
    "qpx_alpha.db"
)


def main():

    print(
        "QPX STEP 12 PAYLOAD INSPECTOR"
    )


    from feature_engine import FeatureEngine
    from signal_engine import SignalEngine


    print("\nLoading features...")


    feature_engine = FeatureEngine(DB)

    features = feature_engine.run()


    print("\nFEATURE TYPE:")
    print(type(features))

    print("\nFEATURE SAMPLE:")
    pprint.pp(features)


    print("\nGenerating signals...")


    signal_engine = SignalEngine()

    signals = signal_engine.generate_signal(
        features
    )


    print("\nSIGNAL TYPE:")
    print(type(signals))


    print("\nSIGNAL PAYLOAD:")
    pprint.pp(signals)



if __name__ == "__main__":
    main()