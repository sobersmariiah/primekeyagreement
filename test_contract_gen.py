import sys
import os

# Add the current directory to sys.path to import generator
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from generator import generate_agreement

class DummyData:
    def __init__(self, **kwargs):
        self.clientName = "John Doe"
        self.loanAmount = 5000.0
        self.annualRatePct = 12.0
        self.loanTermMonths = 12
        self.monthlyPayment = 444.24
        self.firstPaymentDate = "2026-06-28"
        self.agreementDate = "May 12, 2026"
        self.referenceNo = "PRIMEKEY-TEST-2026-001"
        self.currencySymbol = "$"
        for k, v in kwargs.items():
            setattr(self, k, v)

if __name__ == "__main__":
    print("--- Running Success Test ---")
    data = DummyData()
    try:
        pdf_bytes = generate_agreement(data)
        output_path = "/Users/MAC/Desktop/redesigned_contract_final.pdf"
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)
        print(f"Success: PDF generated at {output_path}")
    except Exception as e:
        print(f"Failed unexpectedly: {e}")

    print("\n--- Running Error Test (Missing Field) ---")
    bad_data = DummyData()
    del bad_data.loanAmount
    try:
        generate_agreement(bad_data)
        print("Error: Should have failed due to missing field")
    except RuntimeError as e:
        print(f"Caught expected error: {e}")

    print("\n--- Running Error Test (Invalid Date) ---")
    bad_date_data = DummyData(firstPaymentDate="invalid-date")
    try:
        generate_agreement(bad_date_data)
        print("Error: Should have failed due to invalid date")
    except RuntimeError as e:
        print(f"Caught expected error: {e}")
