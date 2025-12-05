# LSST Forum Data Extraction

## Overview
This script scrapes discussions from the LSST community forum [`https://community.lsst.org`](https://community.lsst.org) and stores the extracted questions and answers into a CSV file. It supports incremental scraping by appending only new discussions since the last recorded scrape. The forum uses pagination, so the script iterates through multiple pages until no more topics are found. The script also includes a delay (`delay=2` seconds) between API requests to avoid server overload.

## File Structure
```
.
└── data_extraction
    ├── README.md
    ├── scrape_lsst.py  # Scraper script
    └── scraped_data
        └── lsst_forum_responses.csv # Output file (if exists, new data is appended)
```

## Usage
### Running the Scraper
To start the scraping process, run this command from the root:

```sh
python eval/data_extraction/scrape_lsst.py
```

- If the CSV file exists, the script extracts only new topics and replies.
- If no previous data exists, it scrapes all available topics.

## Output

The scraped data is stored in `scraped_data/lsst_forum_responses.csv` with the following fields:

- `category_id`: Unique ID of the topic's category (For example, category_id of "News" is 7).
- `question_header`: Title of the question.
- `question_author_id`: User ID of the question's author.
- `question`: Full text of the question (HTML tags removed).
- `question_date`: Date when the question was posted/last modified.
- `answer`: Full text of the answer (HTML tags removed).
- `answer_date`: Date when the response was posted/last modified.
- `community_role`: Role of the respondent in the forum.
- `community_visual_badge`: Visual flair/badge associated with the respondent (will be visible near their username in the forum).
- `is_moderator`: Whether the user has moderator privileges or not (Yes/No).
- `is_admin`: Whether the user has administrative privileges or not (Yes/No).
- `is_staff`: Indicates whether the user is part of the official staff (Yes/No) ("staff" refers to the collective of moderators and admins, while admins have greater control over the forum and its settings compared to moderators, who primarily focus on content moderation).
- `is_accepted_answer`: Denotes whether the answer has been marked as the accepted solution to the question (Yes/No). When the `is_accepted_answer` = 1, it means the answer has been marked as the accepted solution by the questioner. For more reference, refer to this [post](https://community.lsst.org/t/how-to-mark-a-solution/8199).




