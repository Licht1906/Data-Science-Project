# Review kiến trúc pipeline crawl + preprocessing review nghi vấn trên Tiki

## 1. Nhận định nhanh

Pipeline hiện tại đã có khung đúng cho giai đoạn đầu:

1. `CRAWLER/dags/dag_crawl_tiki.py` search keyword, chọn sản phẩm, crawl review, crawl user và ghi raw vào PostgreSQL.
2. `PREPROCESSING/dags/dag_clean_label.py` đọc `raw_reviews`, join thêm `raw_users` và `raw_products`, clean text, deduplicate theo `review_id`, gán nhãn heuristic rồi ghi `processed_reviews`.
3. `streamlit_app.py`/`CRAWLER/dashboard.py` theo dõi số liệu crawl và kết quả preprocessing.

Tuy nhiên, nếu mục tiêu là phát hiện review ảo/review nghi vấn ở mức data science, pipeline vẫn đang nghiêng về demo crawl hơn là một pipeline dữ liệu có thể audit, tái chạy, đo chất lượng và phát triển model.

## 2. Các điểm chưa hợp lý và cách khắc phục

### 2.1. Thiếu phân tầng dữ liệu rõ ràng

Hiện `raw_reviews` là nơi vừa lưu dữ liệu lấy từ Tiki vừa bị upsert mỗi lần crawl. `processed_reviews` chỉ lưu text clean và nhãn, chưa lưu đủ feature trung gian để kiểm tra lại lý do nhãn.

Rủi ro:

- Khó audit một review đã thay đổi qua các lần crawl.
- Khó biết nhãn thay đổi do rule đổi, raw data đổi, hay user/product context đổi.
- Không có lớp feature riêng để dùng cho EDA/modeling.

Cách khắc phục:

- Giữ `raw_reviews` gần với dữ liệu nguồn nhất có thể.
- Tạo thêm bảng/lớp `review_features` hoặc mở rộng `processed_reviews` với các feature quan trọng: `content_char_count`, `content_word_count`, `has_photo`, `has_video`, `sentiment_score`, `duplicate_text_group`, `days_since_user_join`, `user_review_count_bucket`, `rating_deviation_from_product`.
- Lưu `raw_payload` dạng JSONB nếu có thể, ít nhất trong giai đoạn phát triển, để không mất trường Tiki chưa dùng.

### 2.2. Deduplicate mới dựa vào `review_id`

Trong `PREPROCESSING/dags/dag_clean_label.py`, pipeline sort theo `review_id`, `crawled_at` rồi drop duplicate theo `review_id`. Cách này chỉ xử lý duplicate kỹ thuật, chưa phát hiện review trùng nội dung hoặc gần giống nhau.

Rủi ro:

- Một cụm review copy-paste với các `review_id` khác nhau vẫn đi qua.
- Heuristic "trùng lặp" chưa thật sự được triển khai dù đây là dấu hiệu quan trọng của review nghi vấn.

Cách khắc phục:

- Deduplicate kỹ thuật: giữ `review_id` là khóa chính.
- Deduplicate nội dung: tạo `content_hash` sau clean, group theo `content_clean`/`content_hash`.
- Near-duplicate: dùng char n-gram TF-IDF cosine similarity, MinHash/LSH hoặc sentence embeddings khi chuyển sang modeling.
- Thêm flag: `r_duplicate_content_same_product`, `r_duplicate_content_cross_product`, `r_near_duplicate_content`.

### 2.3. User crawler có khả năng không lấy được đủ tín hiệu hành vi

`ReviewCrawler._normalize_review()` đã lấy được `created_by.reviews_count`, nhưng `crawl_users()` lại gọi endpoint customer riêng. Nếu endpoint này bị chặn/trả rỗng, `raw_users.total_reviews` có thể thành 0, làm tăng flag `r_new_or_low_activity_user` sai lệch.

Rủi ro:

- Review bị gắn nghi vấn chỉ vì thiếu dữ liệu user, không phải vì user thật sự ít hoạt động.
- Missing data bị hiểu nhầm là tín hiệu bất thường.

Cách khắc phục:

- Khi insert review, lưu luôn `user_name` và `total_reviews` lấy từ review payload vào một bảng staging hoặc upsert `raw_users` ngay từ review payload.
- Phân biệt `0` và `unknown`: dùng NULL cho thiếu dữ liệu, không fill mặc định thành 0 trước khi labeling.
- Thêm flag riêng `r_missing_user_context` thay vì gộp vào `r_new_or_low_activity_user`.

### 2.4. Heuristic label hiện tại dễ thiên lệch

Trong `PREPROCESSING/labeling.py`, review bị nghi vấn khi có ít nhất 2 flags. Nhiều flags khá hợp lý cho demo, nhưng một số rule dễ bắt nhầm:

- Rating 1 hoặc 5 không luôn đáng nghi; thương mại điện tử thường có phân phối rating lệch 5 sao.
- Comment ngắn không luôn giả; nhiều người mua thật chỉ viết "ok", "tốt".
- `purchased=False` có thể do Tiki không trả field hoặc field đổi tên.
- `helpful_count=0` phổ biến với review mới hoặc sản phẩm ít traffic.

Cách khắc phục:

- Đổi nhãn `is_fake` thành tên đúng bản chất hơn: `is_suspicious` hoặc `heuristic_suspicious`.
- Lưu `flag_count` và `flags` như hiện tại, nhưng thêm `rule_weight` thay vì mọi flag đều ngang nhau.
- Calibrate threshold theo dữ liệu thực tế: xem phân phối flag, tỷ lệ nghi vấn theo category, theo ngày, theo rating.
- Không xem heuristic label là ground truth; chỉ dùng làm weak label hoặc nhãn ưu tiên để con người review.

### 2.5. Preprocessing chưa đủ rõ ràng cho tiếng Việt

Hiện `clean_text()` lower-case, normalize Unicode, bỏ URL, bỏ emoji, nén ký tự lặp. Đây là bước khởi đầu tốt, nhưng preprocessing cho review tiếng Việt nên tách rõ các nhóm việc:

1. Chuẩn hóa kỹ thuật: Unicode NFC, lower-case, bỏ HTML/URL, chuẩn hóa khoảng trắng.
2. Chuẩn hóa nhiễu: emoji, ký tự lặp, spam punctuation, phone/email nếu có.
3. Chuẩn hóa ngôn ngữ: giữ dấu tiếng Việt, xử lý teen code/viết tắt phổ biến nếu cần.
4. Tạo feature: số ký tự, số từ, tỷ lệ dấu câu, tỷ lệ chữ hoa, số câu, có ảnh/video, độ lệch rating so với sản phẩm, thời gian review.
5. Kiểm tra chất lượng: empty rate, duplicate rate, missing user/product context, phân phối rating, phân phối độ dài.
6. Gán nhãn heuristic: dựa trên feature đã tạo, lưu version và flags.

Không nên xóa quá mạnh ở giai đoạn raw/processed đầu tiên vì nhiều tín hiệu nghi vấn nằm trong chính nhiễu: emoji spam, viết hoa, lặp ký tự, dấu chấm than, copy-paste.

### 2.6. Pipeline chưa incremental đúng nghĩa

`dag_clean_label` hiện đọc toàn bộ `raw_reviews` mỗi lần chạy. Khi dữ liệu lớn hơn, cách này sẽ chậm và dễ tạo tải không cần thiết.

Cách khắc phục:

- Dùng watermark trong `crawl_metadata`, ví dụ `last_processed_crawled_at`.
- Chỉ xử lý review mới hoặc review có raw data thay đổi.
- Vẫn cho phép full refresh khi đổi `label_version`.
- Thêm batch id/run id vào metadata để trace từng lần chạy.

### 2.7. Chất lượng crawl chưa được đo đủ

`data_quality_check()` mới đo tổng review, duplicate `review_id`, empty content. Đây là quá ít cho crawler thực tế.

Cách khắc phục:

- Theo dõi HTTP status, retry count, timeout count, 403/429 count theo endpoint.
- Theo dõi số product không có review, số review/page, coverage theo keyword/category.
- Cảnh báo khi `review_count` từ product metadata cao nhưng crawl được rất ít review.
- Lưu snapshot `last_page`, `pages_crawled`, `reviews_inserted`, `reviews_skipped_empty` theo product.

### 2.8. Thiếu ranh giới pháp lý/sản phẩm trong tên biến

Project đang dùng `is_fake`, `fake_probability`. Với bài toán hiện tại, đây không phải kết luận pháp lý mà là heuristic suspicion.

Cách khắc phục:

- Đổi dần tên hiển thị sang "nghi vấn".
- Trong DB có thể giữ tên cũ để tránh migration sớm, nhưng dashboard/report nên ghi rõ là `heuristic_suspicious`.
- Nếu đổi schema sau này: `is_suspicious`, `suspicion_score`, `suspicion_reasons`.

## 3. Preprocessing nên làm gì trong project này?

Ở giai đoạn crawl + preprocessing, mục tiêu preprocessing không phải tạo model ngay, mà là biến raw comment thành dữ liệu sạch, có feature và có thể kiểm tra được.

Đề xuất output tối thiểu của preprocessing:

- `content_clean`: text đã chuẩn hóa nhưng vẫn giữ dấu tiếng Việt.
- `content_char_count`, `content_word_count`: đo độ dài.
- `punctuation_count`, `exclamation_count`, `caps_ratio`: đo spam style.
- `generic_phrase_hit`: có chứa câu khen chung chung không.
- `content_hash`: phát hiện trùng nguyên văn.
- `duplicate_group_size`: số review có cùng nội dung clean.
- `rating`, `rating_deviation_from_product`: rating bất thường so với sản phẩm.
- `purchased`, `helpful_count`: tín hiệu ngữ cảnh.
- `user_total_reviews`, `missing_user_context`: tín hiệu user.
- `flags`, `flag_count`, `suspicion_score`: kết quả heuristic.
- `label_version`, `processed_at`: versioning.

## 4. Tính năng visualize đã bổ sung

Đã mở rộng tab `Preprocessing` trong `CRAWLER/dashboard.py`:

- Join `processed_reviews` với `raw_reviews`, `raw_products`, `raw_users` để có thêm rating, purchased, helpful count, category, thời gian review và user context.
- Thêm metrics: số review đã xử lý, tỷ lệ nghi vấn, median word count, số flag trung bình.
- Thêm Plotly subplot 3x2:
  - Tỷ lệ nhãn heuristic.
  - Phân phối số flag.
  - Độ dài comment sau clean theo nhãn.
  - Rating theo nhãn.
  - Top category có review nghi vấn.
  - Timeline review theo ngày đăng trên Tiki.
- Thêm biểu đồ tần suất từng heuristic flag.
- Thêm nút tải CSV `tiki_processed_reviews.csv`.

Các biểu đồ này giúp trả lời nhanh:

- Rule hiện tại có gắn quá nhiều review là nghi vấn không?
- Review nghi vấn tập trung ở rating nào?
- Review nghi vấn có thật sự ngắn hơn review bình thường không?
- Category/keyword nào đang có nhiều tín hiệu nghi vấn?
- Có ngày nào bất thường về lượng review nghi vấn không?

## 5. Thứ tự ưu tiên khắc phục

1. Đổi cách diễn giải từ "fake" sang "nghi vấn/heuristic suspicious" trong dashboard/report.
2. Thêm feature preprocessing vào DB, không chỉ tính tạm trong dashboard.
3. Phân biệt missing data với giá trị thật bằng NULL và flag riêng.
4. Thêm duplicate/near-duplicate content detection.
5. Làm incremental preprocessing bằng watermark.
6. Bổ sung crawl quality metrics theo product/keyword/endpoint.
7. Sau khi dữ liệu đủ lớn, chuyển heuristic label thành weak label và tạo tập human review nhỏ để đánh giá precision/recall.
