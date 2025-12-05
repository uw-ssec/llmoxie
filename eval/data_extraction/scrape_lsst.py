import requests
import pandas as pd
import time
import os
from tqdm import tqdm
from bs4 import BeautifulSoup

BASE_URL = "https://community.lsst.org"
LATEST_URL = f"{BASE_URL}/latest.json"
CSV_FILENAME = "eval/data_extraction/scraped_data/lsst_forum_responses.csv"

def get_last_scrape_date():
    if os.path.exists(CSV_FILENAME):
        existing_df = pd.read_csv(CSV_FILENAME, parse_dates=["question_date"])
        if not existing_df.empty:
            return existing_df["question_date"].max().strftime("%Y-%m-%d")
    return None

def fetch_topics(page):
    url = f"{LATEST_URL}?page={page}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching page {page}: {e}")
        return None

def fetch_topic_details(topic_id):
    url = f"{BASE_URL}/t/{topic_id}.json"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching topic {topic_id}: {e}")
        return None

def extract_topic_data(topic):
    return {
        "topic_id": topic.get("id"),
        "question": topic.get("title"),
        "question_author": topic.get("posters")[0]["user_id"] if topic.get("posters") else None,
        "question_date": topic.get("created_at"),
        "category_id": topic.get("category_id"),
        "views": topic.get("views"),
        "posts_count": topic.get("posts_count"),
        "last_activity": topic.get("bumped_at")
    }

def extract_reply_data(post, topic_id):
    return {
        "topic_id": topic_id,
        "answer": post.get("cooked"),
        "answer_date": post.get("created_at"),
        "primary_group_name": post.get("primary_group_name"),
        "flair_name": post.get("flair_name"),
        "moderator": post.get("moderator"),
        "admin": post.get("admin"),
        "staff": post.get("staff"),
        "is_accepted_answer": post.get("accepted_answer", False)
    }

def strip_html(text):
    if pd.isna(text):
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text(separator=" ").strip()

def scrape_forum(delay=2, last_scrape_date=None):
    qa_pairs = []
    page = 0
    
    while True:
        print(f"Fetching page {page}...")
        data = fetch_topics(page)
        if not data:
            break

        topics = data.get("topic_list", {}).get("topics", [])
        if not topics:
            print("No more topics found. Stopping.")
            break

        for topic in tqdm(topics, desc=f"Processing Page {page}"):
            topic_data = extract_topic_data(topic)
            
            # Skip topics already scraped
            if last_scrape_date and topic_data["question_date"] <= last_scrape_date:
                print(f"Skipping topic {topic_data['topic_id']} - already scraped.")
                continue

            topic_details = fetch_topic_details(topic_data["topic_id"])
            if topic_details:
                posts = topic_details.get("post_stream", {}).get("posts", [])
                for post in posts[1:]:
                    reply_data = extract_reply_data(post, topic_data["topic_id"])
                    qa_pairs.append({
                        "category_id": topic_data["category_id"],
                        "question_header": topic_data["question"],
                        "question_author_id": topic_data["question_author"],
                        "question": strip_html(posts[0]["cooked"]),
                        "question_date": topic_data["question_date"],
                        "answer": strip_html(reply_data["answer"]),
                        "answer_date": reply_data["answer_date"],
                        "community_role": reply_data["primary_group_name"],
                        "community_visual_badge": reply_data["flair_name"],
                        "is_moderator": reply_data["moderator"],
                        "is_admin": reply_data["admin"],
                        "is_staff": reply_data["staff"],
                        "is_accepted_answer": reply_data["is_accepted_answer"]
                    })
            time.sleep(delay)
        
        page += 1

    return qa_pairs

def main():
    last_scrape_date = get_last_scrape_date()
    print(f"Last scrape date: {last_scrape_date}")
    
    qa_data = scrape_forum(last_scrape_date=last_scrape_date)
    qa_df = pd.DataFrame(qa_data)
    
    if not qa_df.empty:
        qa_df["question_date"] = pd.to_datetime(qa_df["question_date"]).dt.date
        qa_df["answer_date"] = pd.to_datetime(qa_df["answer_date"]).dt.date
        qa_df.sort_values(by=["question_date", "answer_date"], ascending=[False, False], inplace=True)
        qa_df.reset_index(drop=True, inplace=True)
        
        if os.path.exists(CSV_FILENAME):
            existing_df = pd.read_csv(CSV_FILENAME)
            updated_df = pd.concat([existing_df, qa_df], ignore_index=True).drop_duplicates()
        else:
            updated_df = qa_df
        
        updated_df.to_csv(CSV_FILENAME, index=False)
        print("Scraping complete! Data successfully saved.")
    else:
        print("No new data found to append.")

if __name__ == "__main__":
    main()
