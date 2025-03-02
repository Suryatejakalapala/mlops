# MLOps Learning Project

This repository documents my journey through a structured 4-week MLOps learning plan. I'll be updating this README daily to track progress, share insights, and document what I've learned.

## Project Structure

```
mlops-learning/
├── config/             # Configuration files
├── data/               # Datasets (raw, processed, external)
├── docs/               # Documentation
├── models/             # Trained models and configurations
├── notebooks/          # Jupyter notebooks for exploration
├── src/                # Source code organized by functionality
└── tests/              # Unit and integration tests
```

## Setup Instructions

```bash
# Clone repository
git clone https://github.com/yourusername/mlops-learning.git
cd mlops-learning

# Create and activate virtual environment
python -m venv venv

# On Windows
venv\Scripts\activate

# On macOS/Linux
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Learning Progress

### Week 1: Foundations & Environment Setup

#### Day 1 – Introduction to MLOps (Complete)

**What I Learned:**
- MLOps is the practice of applying DevOps principles to machine learning systems
- Key challenges in ML production: reproducibility, versioning, deployment, monitoring
- The full ML lifecycle from data collection to model monitoring
- How MLOps bridges the gap between experimental ML and production-ready systems

**Resources Explored:**
- Made With ML's MLOps Guide
- DataTalksClub's MLOps course overview
- Google Cloud's MLOps Architecture Pattern

**Key Insights:**
- MLOps isn't just about tools but about establishing reliable processes
- The most significant MLOps challenges are often organizational, not technical
- Models can degrade over time due to data drift and concept drift
- Automation is essential for reliable ML systems at scale

**Learning Journal Entry:** Created a dedicated Notion page to document MLOps concepts and best practices.

**MLOps Lifecycle Diagram:** Created a basic diagram showing the key stages: data preparation, model development, deployment, monitoring, and feedback loops.

#### Day 2 – Environment Setup (Complete)

**What I Learned:**
- Best practices for setting up an ML development environment
- The importance of reproducible environments using virtual environments
- How to structure an ML project directory for better organization
- Tools that form the foundation of an MLOps workflow

**Environment Components Installed:**
- Python 3.9 via Anaconda
- Jupyter Notebook and JupyterLab
- VS Code with Python and Jupyter extensions
- Git for version control
- Created GitHub repository for this learning journey

**Project Structure Created:**
- Implemented the cookiecutter data science project structure
- Set up .gitignore with ML-specific patterns
- Configured a virtual environment and requirements.txt

**Key Insights:**
- Environment consistency is crucial for ML reproducibility
- Virtual environments prevent dependency conflicts between projects
- A well-organized project structure saves time and reduces errors
- Documentation should be treated as a first-class citizen from day one

#### Day 3 – Git & GitHub Basics (Complete)

**What I Learned:**
- Core Git commands and workflow for version control
- Best practices for ML project version control
- How to structure branches, commits, and PRs effectively
- Setting up proper gitignore files for ML projects

**Tasks Completed:**
- Initialized repository for the MLOps learning journey
- Practiced git fundamentals: add, commit, push, pull, branch
- Created first PR (Pull Request) with repository structure changes
- Configured .gitignore specifically for ML projects (excluding large data files, model artifacts)
- Set up GitHub Actions for basic CI workflow

**Key Insights:**
- Commit messages should be descriptive and follow consistent conventions
- Branches help isolate development of features/experiments
- Git LFS may be needed for larger model files
- Model versioning requires different approaches than code versioning
- Small, frequent commits are better than large, infrequent ones

**Git Workflow Established:**
- main branch: stable, production-ready code
- develop branch: integration branch for features
- feature branches: for new capabilities or experiments
- Commit convention: `<type>: <description>` (e.g., "feat: add data preprocessing pipeline")

## Next Steps

- Day 4: Introduction to Docker for containerization
- Day 5: Docker in Practice for ML applications
- Complete Week 1 to establish a solid foundation in MLOps tools

## Resources

A collection of helpful resources I've discovered during this learning journey:

- [Made With ML's MLOps Guide](https://madewithml.com/courses/mlops/)
- [Google Cloud's MLOps Architecture Pattern](https://cloud.google.com/architecture/mlops-continuous-delivery-and-automation-pipelines-in-machine-learning)
- [Cookiecutter Data Science Project Template](https://drivendata.github.io/cookiecutter-data-science/)
- [VS Code Python Setup Guide](https://code.visualstudio.com/docs/python/python-tutorial)
- [GitHub Git Cheat Sheet](https://education.github.com/git-cheat-sheet-education.pdf)
- [Interactive Git Branching Tutorial](https://learngitbranching.js.org/)
- [freeCodeCamp Git & GitHub Tutorial](https://www.freecodecamp.org/news/git-and-github-for-beginners/)

---

*This README will be updated daily as I progress through the learning plan.*