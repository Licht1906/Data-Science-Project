# Notebooks

Thư mục này dành cho phần nghiên cứu thủ công của N4/N5:

- `01_EDA.ipynb`: phân phối rating, độ dài review, review theo giờ, top sản phẩm.
- `02_Labeling.ipynb`: kiểm tra 5 rule heuristic và fake rate.
- `03_Feature_Engineering.ipynb`: sanity check feature matrix.
- `04_Modeling.ipynb`: so sánh Logistic Regression, Random Forest, XGBoost theo AUC-PR/F1/AUC-ROC.
- `05_NLP_Analysis.ipynb`: SHAP global và ví dụ waterfall.

Logic production đã được đưa vào `src/` và `dags/`; notebook chỉ nên dùng để EDA, giải thích và xuất hình vào `reports/figures/`.
