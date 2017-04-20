.PHONY: tests unit clean

tests: build
	pytest tests/test_swap.py

ec: build
	python tests/test_ecrecover.py

build: tests/GolemNetworkToken.abi tests/GolemNetworkToken.bin tests/GolemSecretForPaymentSwap.abi tests/GolemSecretForPaymentSwap.bin

tests/GolemNetworkToken.bin: contracts/Token.sol
	solc --bin --abi --optimize contracts/Token.sol | awk '/======= .*GolemNetworkToken =======/,/======= .*MigrationAgent =======/' | grep '[01-9a-f]\{10,\}' > tests/GolemNetworkToken.bin

tests/GolemNetworkToken.abi: contracts/Token.sol
	solc --bin --abi --optimize contracts/Token.sol | awk '/======= .*GolemNetworkToken =======/,/======= .*MigrationAgent =======/' | grep '\[.*\]' > tests/GolemNetworkToken.abi


tests/GolemSecretForPaymentSwap.bin: contracts/Swap.sol
	solc --bin --abi --optimize contracts/Swap.sol | awk '/======= .*GolemSecretForPaymentSwap =======/{flag=1} flag' | grep '[01-9a-f]\{10,\}' > tests/GolemSecretForPaymentSwap.bin

tests/GolemSecretForPaymentSwap.abi: contracts/Swap.sol
	solc --bin --abi --optimize contracts/Swap.sol | awk '/======= .*GolemSecretForPaymentSwap =======/{flag=1} flag' | grep '\[.*\]' > tests/GolemSecretForPaymentSwap.abi

clean:
	rm -f tests/*.bin tests/*.abi
