import sys

if len(sys.argv) > 1 and sys.argv[1] == "init":
    from trade_pipeline.cli.init_wizard import run_init
    run_init()
else:
    from trade_pipeline.pipeline.main import main
    main()
