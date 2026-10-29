CREATE TABLE IF NOT EXISTS articles (
  id CHAR(36) PRIMARY KEY,
  slug VARCHAR(180) NOT NULL UNIQUE,
  title VARCHAR(300) NOT NULL,
  summary VARCHAR(600) NULL,
  body_html LONGTEXT NOT NULL,
  cover_url VARCHAR(800) NULL,
  status ENUM('draft','published') NOT NULL DEFAULT 'draft',
  author_id VARCHAR(64) NOT NULL,
  author_name VARCHAR(200) NULL,
  published_at DATETIME NULL,
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  KEY ix_articles_status_published (status, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS article_revisions (
  id CHAR(36) PRIMARY KEY,
  article_id CHAR(36) NOT NULL,
  body_html LONGTEXT NOT NULL,
  author_id VARCHAR(64) NULL,
  created_at DATETIME NOT NULL,
  KEY ix_revisions_article (article_id, created_at),
  CONSTRAINT fk_revisions_article FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS media (
  id CHAR(36) PRIMARY KEY,
  filename VARCHAR(255) NOT NULL,
  content_type VARCHAR(100) NOT NULL,
  path VARCHAR(500) NOT NULL,
  alt VARCHAR(300) NULL,
  uploaded_by VARCHAR(64) NOT NULL,
  created_at DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS comments (
  id CHAR(36) PRIMARY KEY,
  article_id CHAR(36) NOT NULL,
  user_id VARCHAR(64) NOT NULL,
  user_name VARCHAR(200) NOT NULL,
  body TEXT NOT NULL,
  status ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  created_at DATETIME NOT NULL,
  KEY ix_comments_article_status (article_id, status, created_at),
  CONSTRAINT fk_comments_article FOREIGN KEY (article_id) REFERENCES articles(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
