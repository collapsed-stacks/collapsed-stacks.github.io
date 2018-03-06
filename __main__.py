#!/usr/bin/env python3.6
# by Jeremy Banks <_@jeremy.ca>
# released under the 0BSD license


from collections import defaultdict
from enum import IntEnum
from glob import glob
from json import dumps, loads, dump, load
from logging import DEBUG, basicConfig as basic_logging_config, getLogger as get_logger
from os import makedirs, remove
from os.path import abspath, dirname
from re import sub
from shutil import rmtree
from textwrap import dedent
from types import SimpleNamespace
from xml.etree import ElementTree


logger = get_logger(__name__)


def main():
    basic_logging_config(level=DEBUG)
    logger.debug(f"main()")

    clean_everything()
    copy_xml_dump_to_json_lines()
    update_config_and_readme()
    dump_markdown_from_json_lines()
    hacky_suggestion()


def clean_everything():
    logger.debug(f"clean_everything()")

    for filename in glob('data/**/*.jsonl'):
        remove(filename)

    rmtree('questions', ignore_errors=True)
    rmtree('users', ignore_errors=True)
    rmtree('tags', ignore_errors=True)


def copy_xml_dump_to_json_lines():
    logger.debug(f"copy_xml_dump_to_json_lines()")

    integer_field_suffixes = [
        'Id',
        'Count',
        'Score',
        'Reputation',
        'Age',
        'Votes,'
        'Views',
    ]

    for xml_filename in glob('data/**/*.xml'):
        json_filename = xml_filename[:-len('xml')] + 'jsonl'

        logger.debug(f"  from {xml_filename}")
        logger.debug(f"  to {json_filename}")

        try:
            with open(xml_filename, 'rb') as xml_file, open(json_filename, 'wt') as json_file:
                first_tag = None
                for (_, row) in ElementTree.iterparse(xml_file):
                    if first_tag is None:
                        first_tag = row.tag
                    elif row.tag != first_tag:
                        break

                    data = {
                        k: int(v or 0) if any(k.endswith(s) for s in integer_field_suffixes) else v
                        for (k, v) in row.attrib.items()
                    }

                    if 'Tags' in data:
                        data['Tags'] = data['Tags'].strip('><').split('><')

                    json_line = dumps(data)

                    assert '\n' not in json_line

                    json_file.write(json_line)
                    json_file.write('\n')
        except ElementTree.ParseError as e:
            logger.error(e)


def update_config_and_readme():
    logger.debug(f"update_config_and_readme()")

    with open('_config.yml', 'rt') as f:
        config = load(f)

    stack_config = config['stack_site']
    site_name = stack_config['name']
    site_slug = stack_config['slug']
    proposal_id = stack_config['proposal_id']

    new_config = {
        'stack_site': {
            'name': stack_config['name'],
            'slug': stack_config['slug'],
            'proposal_id': stack_config['proposal_id']
        },
        'title': f'{stack_config["name"]} Archive',
        'exclude': ['data']
    }

    with open('_config.yml', 'wt') as f:
        dump(new_config, f, sort_keys=True, indent=2)
        f.write('\n')

    first_year = float('infinity')
    last_year = float('-infinity')

    post_ids = set()

    with open(f'data/main/PostHistory.jsonl') as f:
        for line in f:
            if not line: continue
            row = loads(line)
            post_ids.add(row['PostId'])
            year = int(row['CreationDate'][:4])
            first_year = min(first_year, year)
            last_year = max(last_year, year)

    post_count = len(post_ids)

    if first_year == last_year:
        years_short = f'{first_year}'
        years_long = f'in {first_year}'
    else:
        years_short = f'{first_year}-{last_year}'
        years_long = f'from {first_year} to {last_year}'

    with open(f'README.md', 'wt') as f:
        f.write(
            f"This is an archive of the **{site_name}** Q&A site that existed {years_long}. "
            f"The official proposal and archive of the site [may be found on Stack Exchange Area "
            f"51](https://area51.stackexchange.com/proposals/{proposal_id}). All content is "
            f"licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-"
            f"sa/3.0/).\n\n")
        f.write(
            f"This archive includes browsable copies of the {post_count} questions and answers "
            f"that existed on the site at the time it was shut down. Each page is a simple "
            f"markdown file, which may be automatically rendered into a HTML template by GitHub "
            f"Pages. There is [an index page listing all of the site's `questions/`](https://"
            f"collapsed-stacks.github.io/{site_slug}/questions/), but it's are more suited to "
            f"consumption by robots than humans.\n\n")
        f.write(
            f"The `data/` directory includes a copy of contents of the official data dump from "
            f"Area 51. We also add [JSON Lines](http://jsonlines.org/) versions of every XML file "
            f"for convenience. You can grab this from [GitHub at collapsed-stacks/{site_slug}]"
            f"(https://github.com/collapsed-stacks/{site_slug}).\n")

def dump_markdown_from_json_lines():
    logger.debug(f"dump_markdown_from_json_lines()")

    logger.debug(f"  loading jsonl tables")

    def load_table(name):
        logger.debug(f"  load_table({repr(name)})")

        with open(f'data/main/{name}.jsonl') as f:
            return {
                row.Id: row
                for row in (
                    SimpleNamespace(**loads(line))
                    for line in f if line.strip()
                )
            }

    AllUsers = load_table('Users')
    try:
        Posts = load_table('Posts')
    except:
        PostsWithDeleted = load_table('PostsWithDeleted')
        Posts = {
            post.Id: post
            for post in PostsWithDeleted.values()
            if not hasattr(post, 'DeletionDate')
        }
    Comments = load_table('Comments')

    logger.debug(f"  enriching data structures")

    class PostTypeId(IntEnum):
        QUESTION = 1
        ANSWER = 2

    Users = {-1: AllUsers[-1]}
    COMMUNITY = Users[-1]

    Questions = {
        p.Id: p for p in Posts.values() if p.PostTypeId == PostTypeId.QUESTION}
    Answers = {
        p.Id: p for p in Posts.values() if p.PostTypeId == PostTypeId.ANSWER}

    Tags = defaultdict(list)

    for post in Posts.values():
        if hasattr(post, 'OwnerUserId'):
            post.Owner = Users[post.OwnerUserId] = AllUsers[post.OwnerUserId]
        else:
            post.Owner = COMMUNITY

        post.Edited = hasattr(post, 'LastEditDate')
        post.BodySource = post.Body

    for question in Questions.values():
        question.Answers = []

        question.Slug = sub('[^a-z0-9]+', '-', question.Title[:80].lower()).strip('-') or f'post{question.Id}'
        question.Path = f'questions/{question.Id}/{question.Slug}'

        if hasattr(question, 'AcceptedAnswerId'):
            question.AcceptedAnswer = Answers.get(question.AcceptedAnswerId)
            if not question.AcceptedAnswer:
                logger.error(f"Failed to find accepted answer with ID {question.AcceptedAnswerId}.")
        else:
            question.AcceptedAnswer = None

        for tag in question.Tags:
            Tags[tag].append(question)

    for answer in Answers.values():
        question = Questions[answer.ParentId]
        answer.Question = question
        answer.IsAccepted = answer == question.AcceptedAnswer
        question.Answers.append(answer)
        question.Answers.sort(key=lambda a: -a.Score)
        answer.Path = f'questions/{question.Id}/{question.Slug}#answer-{answer.Id}'

    for user in Users.values():
        user.Slug = sub('[^a-z0-9]+', '-', user.DisplayName[:80].lower()).strip('-') or f'user{user.Id}'
        if hasattr(user, 'AccountId'):
            user.Url = f'https://stackexchange.com/users/{user.AccountId}/{user.Slug}'
        else:
            user.Url = f'https://stackexchange.com/users/-1/{user.Id}-{user.Slug}'

    logger.debug(f"  loading post sources from history")

    with open(f'data/main/PostHistory.jsonl') as f:
        for revision in (
                SimpleNamespace(**loads(line))
                for line in f if line.strip()):
            if revision.PostHistoryTypeId not in (2, 5, 8):
                continue # doesn't affect post bodies
            post = Posts[revision.PostId]
            post.BodySource = revision.Text.replace('\r\n', '\n').replace('\r', '\n')

    logger.debug(f"  generating markdown for question pages")

    makedirs('questions', exist_ok=True)

    for question in Questions.values():
        logger.debug(f"    {question.Path}")

        makedirs(f'questions/{question.Id}', exist_ok=True)

        with open(f'{question.Path}.md', 'wt', encoding='utf-8') as f:
            f.write(f'''\
## {question.Title}

- posted by: [{question.Owner.DisplayName}]({question.Owner.Url}) on {question.CreationDate.split('T')[0]}
- tagged: {", ".join(f"`{tag}`" for tag in question.Tags)}
- score: {question.Score}

{question.BodySource}

''')

            if question.Answers:
                for answer in sorted(question.Answers, key=lambda a: (-a.Score, a.Id)):

                    f.write(f'''
## Answer {answer.Id}

- posted by: [{answer.Owner.DisplayName}]({answer.Owner.Url}) on {answer.CreationDate.split('T')[0]}
- score: {answer.Score}

{answer.BodySource if not
    ('][' in answer.BodySource and
    ' [' in answer.BodySource) else answer.Body}

''')
            else:
                f.write('## No Answers\n\nThere were no answers to this question.\n')

            f.write("\n\n---\n\nAll content is licensed under [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).\n")

    logger.debug(f"  generating questions index page")

    with open(f'questions/index.md', 'wt', encoding='utf-8') as f:
        f.write("## All Questions\n\n")
        for question in sorted(Questions.values(), key=lambda q: (-q.Score, q.Id)):
            f.write(f" - [{question.Title}](../{question.Path})\n")


def hacky_suggestion():
    print()
    print("If you'd now like to (re-)create a deterministic git repo of this ")
    print("directory, consider running the following in Bash:")
    print("")
    print("  git init;")
    print("  git checkout --detach;")
    print("  git branch -D master;")
    print("  git checkout --orphan master;")
    print("  git add . && ")
    print("  GIT_COMMITTER_DATE='Thu Jan  1 00:00:00 UTC 1970' \\")
    print("  GIT_COMMITTER_NAME=' ' \\")
    print("  GIT_COMMITTER_EMAIL='\\<\\>' \\")
    print("  GIT_AUTHOR_DATE='Thu Jan  1 00:00:00 UTC 1970' \\")
    print("  GIT_AUTHOR_NAME=' ' \\")
    print("  GIT_AUTHOR_EMAIL='\\<\\>' \\")
    print("  git commit \\")
    print("  --allow-empty-message -m '' \\")
    print("  --allow-empty;")
    print()


if __name__ == '__main__':
    import sys
    sys.exit(main(*sys.argv[1:]))
