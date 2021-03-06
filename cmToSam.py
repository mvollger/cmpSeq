#!/usr/bin/env python
import argparse

parser = argparse.ArgumentParser(description="parses the output of cross match, cross match must be run with the flags -alignment and -tags, does not support inputs with qualities")
parser.add_argument("input", help="cross_match output file, must have been run with -tags and -alignment" )
parser.add_argument("out", help="outputfile of this prgram" )
parser.add_argument('-d', action="store_true", default=False)
parser.add_argument('--blast', "-b", help="""Tabular blast input with some required feilds. 
The out format must be set to 7 and have these fields:
"score sstrand qseqid qstart qend qlen qseq sseqid sstart send slen sseq"
However, these feilds can be in any order you want and you can also include additional ones without problems.
The program will NOT work with format 6.
""", action="store_true", default=False)
args = parser.parse_args()
DEBUG=args.d

import re
import numpy as np
import pysam 
from collections import Counter
import sys
if( sys.version_info[0] < 3 ): 
	from StringIO import StringIO
else:
	from io import StringIO

M=0 #M	BAM_CMATCH	0
I=1 #I	BAM_CINS	1
D=2 #D	BAM_CDEL	2
N=3 #N	BAM_CREF_SKIP	3
S=4 #S	BAM_CSOFT_CLIP	4
H=5 #H	BAM_CHARD_CLIP	5
P=6 #P	BAM_CPAD	6
E=7 #=	BAM_CEQUAL	7
X=8 #X	BAM_CDIFF	8
B=9 #B	BAM_CBACK	9
NM=10 #NM	NM tag	10
conRef	=	[M, D, N, E, E] # these ones "consume" the reference
conQuery=	[M, I, S, E, X] # these ones "consume" the query
conAln	=	[M, I, D, N, S, E, X] # these ones "consume" the alignments
# format for the output table 


#
# read the header of a alignmnet
#
def readCMline(line):
	line = line.split()
	# drop the tag that says ALIGNMENT
	line = line[1:]
	# ['17625', '1.81', '0.25', '0.56', 'chr1:223822113-224042658', '139281', '158695', '61851', 'C', 'AC270130.1', '117267', '97912', '81891']

	# check if it is a complement
	complement = False
	if("C" in line):
		complement = True

	# tells me to drop the line because it is a subset of another
	if("*" in line):
		line = line[:-1]
		#return(None)

	# check line length
	assert len(line) == 12 + complement
	
	# move the extenshion of the sequence past the aln to match the regualr locaiton
	if(complement):
		extend = line.pop(10)
		line.append(extend)
	# a a Not complement tag to the line if NC
	if(not complement):
		line.insert(8, "NC")
	
	line = re.sub('\(|\)', '', "\t".join(line))
	return( line.split() )

#
# read the alignment  
#
def readAln(cmString):
	lines = cmString.split("\n")
	# skip if there are no lines in the aln
	if(len(lines) < 5):
		return((None, None))

	# move off of header and onto aln
	idx = 2

	fasta1 = ""
	fasta2 = ""
	while(True):
		if( idx + 2 >= len(lines) ):
			#print(idx, len(lines))
			break
		# qfasta
		seq1 = ("_" + lines[idx]).split()
		# rfasta
		seq2 = ("_" + lines[idx+2]).split()
		# update seqs
		fasta1 += seq1[3]
		fasta2 += seq2[3]
		
		idx += 4
	
	#extend = int( header[-1] ) * "-"
	#fasta1= "-"*start2 + fasta1 + extend
	#fasta2= "-"*start2 + fasta2 + extend
	#rtn = (header,  [start1, end1, start2, end2, fasta1, fasta2] )
	
	rtn = (fasta1, fasta2)
	return(rtn)

# need this global varible so I can set the flag for the best alignment 
FLAGS = {}
# need this for adding reference sequences 
REFS = {}

# pass a string that contains the alignmnet
class cmAln:

		
	# step then the amound it should sum to 
	def checkLength(self):
		counter = 0
		for char in self.lcigar:
			if char in ["M", "I", "S", "=", "X"]:
				counter += 1
		assert len(self.seq) == counter, (len(self.seq), counter, Counter(self.seq), Counter(self.qaln),
											Counter(self.raln))


	
	def __init__(self, cmString, blast = args.blast ):
		if(not blast):
			self.createHeader(cmString)
			self.getAln(cmString)
		else:
			# the blast line is only one thing long, so we make it all at once 
			self.blastReadIn(cmString)

		self.createCigar() 
		self.miscSam()
		self.checkLength()
		
		# update flags if this is the best match
		if(self.qname not in FLAGS):
			FLAGS[self.qname] = self.score
		if(self.score > FLAGS[self.qname]):
			FLAGS[self.qname] = self.score
		
		# update ref length if not alreay there
		if(self.rname not in REFS):
			REFS[self.rname] = self.tlen
		
	
	def createCigar(self):
		assert(len(self.qaln) == len(self.raln))
		# query base and reference base
		# add hard masked end
		cigar = "H" * self.qstart
		alpha = ["A", "G", "C", "T", "a", "g", "c", "t"]
		# uncollpased cigar string
		for qb, rb in zip(self.qaln, self.raln):
			if(qb in alpha and rb in alpha and qb.lower() == rb.lower()): # base pair match 
				cigar += "="
			elif(rb == "-"): # insertion relative to reference
				cigar += "I"
			elif(qb == "-"): # deletion relative to reference
				cigar += "D"
			elif(qb in alpha and rb in alpha and qb.lower() != rb.lower()): # mismatch
				cigar += "X"
			elif(qb == "N" and rb in alpha): # not sure what to do in this case
				cigar += "M"
			elif(rb == "N"): # not sure about this case
				cigar += "M"
			else:
				print("case not handled", qb, rb)
				exit()
		cigar += "H" * self.qext
		self.lcigar = cigar 

		# collapse cigar string
		self.cigar = ""
		counter = 0
		pre = cigar[0]
		total = 0
		for cur in cigar:
			if(pre == cur):
				counter += 1
				total +=1 
			else:
				self.cigar += "{}{}".format(counter, pre)
				counter = 1
				total += 1
			pre = cur
		self.cigar += "{}{}".format(counter, pre)
		
		assert len(cigar) == total, ("cigar not made correctly", len(cigar), total)
		self.total = total

	# easy things to calculate for the sam file
	def miscSam(self):
		self.flag = 2
		self.pos = self.rstart + 1
		if(self.complement):
			self.flag += 16
		self.mapq = int( np.log10(self.score) )
		self.rnext = "*"
		self.pnext = 0
		self.tlen = self.rend + self.rext  
		self.seq = re.sub('-', '', self.qaln)
		self.qual = "*"

	def getAln(self, cmString):
		(self.qaln, self.raln) = readAln(cmString)

	def createHeader(self, cmString):
		headerLine = cmString.split("\n")[0]
		#print(headerLine)
		header = readCMline(headerLine)
		
		self.score = int(header[0])
		self.sub = float(header[1]) 
		self.deletion = float(header[2])
		self.ins = float(header[3])
		self.qname = header[4]
		self.qstart = int(header[5])
		self.qend = int(header[6])
		self.qext = int(header[7])
		self.complement = False
		if(header[8] == "C"):
			self.complement = True
		self.rname = header[9]
		self.rstart = int(header[10])
		self.rend = int(header[11])
		self.rext = int(header[12]) 
		if(self.complement):
			temp = self.rstart
			self.rstart = self.rend
			self.rend = temp

	def blastReadIn(self, cmString):
		# this is also the only line in a blast aln
		headerLine = cmString.split("\n")[0]
		#print(headerLine)
		header = headerLine.split()	
		self.score = int(header[0])
		self.sub = float(header[1]) 
		self.deletion = float(header[2])
		self.ins = float(header[3])
		self.qname = header[4]
		self.qstart = int(header[5])
		self.qend = int(header[6])
		self.qext = int(header[7])
		self.complement = False
		if(header[8] == "C"):
			self.complement = True
		self.rname = header[9]
		self.rstart = int(header[10])
		self.rend = int(header[11])
		self.rext = int(header[12]) 
		self.qaln = header[13]
		self.raln = header[14]


	# the string return is the sam file 
	def __str__(self):
		sam = ("{}\t"*10 + "{}\n").format(
				self.qname, self.flag, self.rname,
				self.pos, self.mapq, self.cigar, 
				self.rnext, self.pnext, self.tlen,
				self.seq, self.qual)
		return(sam)


#
#
#
def convertBlastToCm(aln):
	import pandas as pd
	aln = StringIO(aln)
	aln = pd.read_csv(aln, sep = "\t")
	sams = []	
	for idx, row in aln.iterrows():
		complement = "NC"
		if(row["subject strand"] == "minus"):
			complement = "C"
		blast  = ("{}\t"*14 + "{}\n").format( row["score"], 0.0 , 0.0 , 0.0, 
				row["query id"], row["q. start"], row["q. end"], row["query length"] - row["q. end"], 
				complement, 
				row["subject id"], row["s. start"], row["s. end"], row["subject length"] - row["s. end"], 
				row["query seq"], row["subject seq"])
		sams.append( cmAln(blast) )

	return(sams)

#
#
# read in the file
def read(myfile):
	lines = open(myfile).readlines()
	idx = 0
	alns = []
	while(idx < len(lines) ):
		line = lines[idx]
		# if this is true then we are in a alignment section
		if("ALIGNMENT" in line):
			aln = ""
			# read whole alignment into a string
			while(idx < len(lines)):
				line = lines[idx]
				if("Transitions" in line):
					break
				aln += line
				idx += 1
			alns.append( cmAln(aln) )
		# out side of alignment, move until instide one
		idx += 1
	return(alns)



#
# this reads in a blast alignment and convertes it to sam. 
#
def readInBlast(myblast):
	f = open(myblast)
	toKeep = ""
	header = ""
	for line in f:
		if( (header == "") and ("# Fields:" in line) ):
			# make header
			header = line.split(":")[1]
			header = header.split(",")
			header = [token.strip() for token in header]
			header = "\t".join(header) + "\n"
		if(line[0] != "#" ):
			toKeep += ( "\t".join( line.strip().split() ) + "\n" )
	
	sams = convertBlastToCm(header + toKeep)	
	
	return(sams)
	

# read in all the of alignmnets 
if(args.blast):
	cmAlns = readInBlast(args.input)
else:
	cmAlns = read(args.input)


samHeader = """@HD\tVN:1.4\tSO:coordinate
@PG\tID:cmToSam.py\tCL:cmToSam.py {} {} 
@CO\tThis is a cross match alignmnet turned into a sam file.
@CO\tThis conversion is still in alpha, possible issues include generating the correct "FLAG" for the sam file
@CO\tThe mapq value is the log10 of the SM score from cross_match rounded down
@CO\tThe converter is called cmToSam.py and was written by Mitchell Vollger
""".format(args.input, args.out)

for key in REFS:
	samHeader += "@SQ\tSN:{}\tLN:{}\n".format(key, REFS[key])



sam = samHeader

for aln in cmAlns:
	if( aln.score == FLAGS[aln.qname] ):
		aln.flag -= 2
	sam += str(aln)

open(args.out, "w+").write(sam)




