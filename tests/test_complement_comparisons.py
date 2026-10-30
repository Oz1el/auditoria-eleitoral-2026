import duckdb
import pytest
from auditoria_urnas.complement_comparisons import municipal_round_comparison


def test_round_comparison_year_alias_and_full_outer_coverage():
    with duckdb.connect() as db:
        db.execute('create table votes(year integer,turn integer,uf varchar,municipio integer,number integer,votes bigint)')
        db.executemany('insert into votes values (?,?,?,?,?,?)',[
            (2026,1,'RR',1,13,60),(2026,1,'RR',1,22,40),(2026,1,'RR',1,95,20),(2026,1,'RR',1,96,30),
            (2026,2,'RR',1,13,55),(2026,2,'RR',1,22,45),
            (2026,2,'RR',2,13,70),(2026,2,'RR',2,22,30),
            (2026,1,'ZZ',3,13,10),(2026,1,'ZZ',3,22,10)])
        result=municipal_round_comparison(db).set_index(['uf','municipio'])
    assert len(result)==3 and result['year'].tolist()==[2026]*3
    assert result.loc[('RR',1),'share_first']==pytest.approx(.6)
    assert result.loc[('RR',1),'share_second']==pytest.approx(.55)
    assert result.loc[('RR',1),'share_change']==pytest.approx(-.05)
    assert result.loc[('RR',1),'valid_first']==100
    assert result.loc[('RR',2),'share_second']==pytest.approx(.7)
    assert result.loc[('RR',2),'share_first']!=result.loc[('RR',2),'share_first']
    assert result.loc[('ZZ',3),'share_second']!=result.loc[('ZZ',3),'share_second']
