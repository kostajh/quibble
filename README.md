TLDR:

	docker build --tag quibble .
	docker run -it --entrypoint=/bin/bash --rm quibble

Then run the quibble command:

	ZUUL_URL=https://gerrit.wikimedia.org/r/p ZUUL_BRANCH=master ZUUL_REF=master quibble --packages-source vendor

CACHING
-------

To avoid cloning MediaWiki over the network, you should initialize local bare
repositories to be used as cache to copy from:

    mkdir -p ref/mediawiki/skins
    git clone --bare mediawiki/core ref/mediawiki/core.git
    git clone --bare mediawiki/vendor ref/mediawiki/vendor.git
    git clone --bare mediawiki/skins/Vector ref/mediawiki/skins/Vector.git

We have `XDG_CACHE_HOME=/cache` set which is recognized by package managers.
Create a cache directory writable by any user:

    install --directory --mode 777 cache

We then mount the git repositories as a READ-ONLY volume as `/srv/git` and the
`cache` dir in read-write mode:

    docker run -it --rm -v "$(pwd)"/ref:/srv/git:ro -v "$(pwd)"/cache:/cache quibble

TESTING
-------

Coverage report:

    tox -e cover && open cover/index.html
