from typing import NamedTuple

import rocksdb
from hexbytes import HexBytes
from iavl.diff import Op
from iavl.iavl import NodeDB, Tree


class ExpResult(NamedTuple):
    root_hash: HexBytes
    # the number of orphaned nodes by this version
    orphaned: int


# parsed from the output of `go run ref.go`
# (root hash, number of orphaned nodes)
EXPECT_OUTPUT = [
    ExpResult(None, 0),
    ExpResult(
        HexBytes("6032661AB0D201132DB7A8FA1DA6A0AFE427E6278BD122C301197680AB79CA02"), 0
    ),
    ExpResult(
        HexBytes("457D81F933F53E5CFB90D813B84981AA2604D69939E10C94304D18287DED31F7"), 1
    ),
    ExpResult(
        HexBytes("C7AB142752ADD0374992261536E502851CE555D243270D3C3C6B77CF31B7945D"), 1
    ),
    ExpResult(
        HexBytes("D6D9F6CA091FA4BD3545F0FEDB2C5865D42123B222C202DF72EFB4BFD75CC118"), 2
    ),
    ExpResult(
        HexBytes("585581060957AE2E6157F1790A88BF3544FECC9902BBF2E2286CF7325539126C"), 11
    ),
    ExpResult(
        HexBytes("5C5859808C79637A143FEA9548A19194782D501A15D3EB412240D6A0D040D637"), 4
    ),
    ExpResult(
        HexBytes("D91CF6388EEFF3204474BB07B853AB0D7D39163912AC1E610E92F9B178C76922"), 81
    ),
]


ChangeSets = [
    [(b"hello", Op.Insert, b"world")],
    [(b"hello", Op.Update, (b"world", b"world1")), (b"hello1", Op.Insert, b"world1")],
    [(b"hello2", Op.Insert, b"world1"), (b"hello3", Op.Insert, b"world1")],
    [(b"hello%02d" % i, Op.Insert, b"world1") for i in range(20)],
    [(b"hello", Op.Delete, b"world1"), (b"hello19", Op.Delete, b"world1")],
    # try to cover all balancing cases
    [(b"aello%02d" % i, Op.Insert, b"world1") for i in range(21)],
    # remove most of the values
    [(b"aello%02d" % i, Op.Delete, b"world1") for i in range(21)]
    + [(b"hello%02d" % i, Op.Delete, b"world1") for i in range(19)],
]


def apply_change_set(tree: Tree, changeset):
    for key, op, arg in changeset:
        if op == Op.Insert:
            tree.set(key, arg)
        elif op == Op.Update:
            _, value = arg
            tree.set(key, value)
        elif op == Op.Delete:
            tree.remove(key)
        else:
            raise NotImplementedError(f"unknown op {op}")


def setup_test_tree(kvdb: rocksdb.DB):
    db = NodeDB(kvdb)
    tree = Tree(db, 0)
    apply_change_set(tree, ChangeSets[0])
    tree.save_version()

    tree = Tree(db, 1)
    assert b"world" == tree.get(b"hello")
    apply_change_set(tree, ChangeSets[1])
    tree.save_version()

    tree = Tree(db, 2)
    assert b"world1" == tree.get(b"hello")
    assert b"world1" == tree.get(b"hello1")
    apply_change_set(tree, ChangeSets[2])
    tree.save_version()

    tree = Tree(db, 3)
    assert b"world1" == tree.get(b"hello3")

    node = db.get(db.get_root_hash(3))
    assert 2 == node.height

    apply_change_set(tree, ChangeSets[3])
    tree.save_version()

    # remove nothing
    assert tree.remove(b"not exists") is None

    apply_change_set(tree, ChangeSets[4])
    tree.save_version()
    assert not tree.get(b"hello")

    apply_change_set(tree, ChangeSets[5])
    tree.save_version()

    # test cache miss
    db = NodeDB(kvdb)
    tree2 = Tree(db)
    assert tree2.version == 6
    assert b"world1" == tree2.get(b"aello20")

    # remove most of the values
    apply_change_set(tree, ChangeSets[6])
    tree.save_version()


def test_basic_ops(tmp_path):
    """
    the expected root hashes are generated by equivalent golang code:
    $ go run ./ref.go
    """
    dbpath = tmp_path / "basic_ops"
    dbpath.mkdir()
    print("db", dbpath)
    kvdb = rocksdb.DB(str(dbpath), rocksdb.Options(create_if_missing=True))
    setup_test_tree(kvdb)

    for i in range(1, len(EXPECT_OUTPUT)):
        tree = Tree(NodeDB(kvdb), i)
        assert EXPECT_OUTPUT[i].root_hash == tree.root_node_ref

    # test cache miss
    db = NodeDB(kvdb)
    tree2 = Tree(db, 6)
    assert tree2.version == 6
    assert b"world1" == tree2.get(b"aello20")


def test_empty_tree(tmp_path):
    dbpath = tmp_path / "empty-tree"
    dbpath.mkdir()
    db = NodeDB(rocksdb.DB(str(dbpath), rocksdb.Options(create_if_missing=True)))

    tree = Tree(db)
    assert tree.version == 0

    tree = Tree(db, 0)
    assert tree.get("hello") is None
    assert tree.remove("hello") is None
    tree.save_version()
    assert tree.version == 1
