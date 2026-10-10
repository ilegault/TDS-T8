with open("t8_daq_system/rig/tungsten_model.py", "r") as f:
    content = f.read()
print("R_COLD = 0.033 in file?", "R_COLD = 0.033" in content)
print("R_COLD = 0.005 in file?", "R_COLD = 0.005" in content)
