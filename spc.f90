	dimension a(0:1024,0:1024),b(0:1024,0:1024)
        dimension aminb(0:1024,0:1024),mminb(0:1024,0:1024)
        dimension mode(0:100000)
	
	dimension vo(-10000:10000), vop(-10000:10000),vo2(-10000:10000,10), vo3(-10000:10000,10)
	vo=0
	vo2=0
	vo3=0
	vop=0
	
	a=0
	b=0
        
        l_donothing = 0 ! electrostatic back in time
        !l_donothing = 1 ! actually do nothing and return
        	!l_donothing = 2 ! 3x3 box sweep
        l_back = 0 ! don't remove background
        !l_back = 1 ! remove background

	open(unit=2,file='workfile')
        
        do i=1,1024
	do j=1,1024
            read (2,*) a(i,j)
        end do
        end do
        
        write(*,*) "read"
        
		nblock=1024
	
        isize_sm = 50
        jsize=1024/isize_sm
        do i1 = 0,jsize
            do j1 = 0,jsize
                amin_h=10000.
                mode = 0
	do i=1,1024
	do j=1,1024
            if (i/isize_sm == i1) then
                if (j/isize_sm == j1) then
	
	amin_h=min(amin_h,a(i,j))
        mode(int(a(i,j))) = mode(int(a(i,j))) + 1
                end if
            end if
        end do
        end do
        aminb(i1,j1) = amin_h
        max_mode = 0
        max_moden = -1
        do i =0,100000
            if (mode(i)>max_mode) then
                max_mode = mode(i)
                max_moden = i
            end if
        end do
        mminb(i1,j1) = max_moden
        write (67,*) i1,j1,amin_h,max_moden
            end do
	end do
        
        !write (*,*) aminb(0,0:20)
        !write (*,*) aminb(0:20,0)
        
        !pause
        
        if (l_back == 1) then
        do i=1,1024
	do j=1,1024
            a(i,j) = a(i,j) - (mminb(i/isize_sm,j/isize_sm) + (mminb(i/isize_sm,j/isize_sm) - aminb(i/isize_sm,j/isize_sm))*1)
            if (a(i,j) < 0) a(i,j)=0
        end do
        end do
        end if
	
	
	if (l_donothing == 1) then
		do i=1,nblock
		do j=1,nblock
		write (3,*) i-1
		write (3,*) j-1
		write (3,*) a(i,j) !+sub !+aminn
		end do
		end do
		stop
	end if
        
        if (l_donothing == 2) then
            ! simple sweep
            do i=1,nblock-1
		do j=1,nblock-1
                    if (a(i,j) > 0) then
              if ((a(i-1,j) < a(i,j)).and.(a(i+1,j) < a(i,j)).and.(a(i,j-1) < a(i,j)).and.(a(i,j+1) < a(i,j))) then
              if ((a(i-1,j-1) < a(i,j)).and.(a(i+1,j-1) < a(i,j)).and.(a(i+1,j-1) < a(i,j)).and.(a(i+1,j+1) < a(i,j))) then
                  rold = a(i,j)
                  a(i,j) = a(i,j) + a(i-1,j) + a(i+1,j) + a(i,j+1) + a(i,j-1) + a(i+1,j+1) + a(i-1,j+1)+ a(i-1,j-1)+ a(i+1,j-1)
                  a(i-1,j) =0
                  a(i+1,j) =0
                  a(i,j+1) =0
                  a(i,j-1) =0
                  a(i+1,j+1) =0
                  a(i-1,j+1)=0
                  a(i-1,j-1)=0
                  a(i+1,j-1)=0
                 ! write (*,*) "Found peak", i,j,rold,a(i,j)
              end if
                        end if
                    end if
                end do
            end do
            
            do i=1,nblock
		do j=1,nblock
		write (3,*) i-1
		write (3,*) j-1
		write (3,*) a(i,j) !+sub !+aminn
		end do
		end do
		stop
            
        end if
	
	!	Try to remove background - if a point is small and not near a larger value, remove
	
	cut_back = 0
	do iter=0,5
	do i=1,nblock-1
	do j=1,nblock-1
	igt = 1
	sumer = 0.
	do k1=-1,1
	do k2=-1,1
		if (k1==0.and.k2==0) cycle
		sumer = sumer + a(i+k1,j+k2)
		if (a(i+k1,j+k2).ge.cut_back) then
		igt=0
		exit
		end if
	end do
	end do
	if (igt==1.and.a(i,j)<cut_back) then
	!write (*,*) a(i,j),i,j
	a(i,j)=0.
	end if
	end do
	end do	
	end do
	
	write (*,*) "Subracted null"
	do loop=1,10
	write (*,*) a(loop,1:10)
	end do
	

	
	do i=1,nblock
	write (9,*) i,a(200,i), a(600,i)
	end do	
	
	do i=1,nblock
	do j=1,nblock
	vo(int(a(i,j)))=vo(int(a(i,j)))+1
	end do
	end do
	
	frac=.1
	adiffmin = 0
        a_over = 10
	
	write (*,*) a(1,1:10)
	
	do loop=0,50
	
	do i=1,nblock
	do j=1,nblock-1
	if (abs(a(i,j+1)-a(i,j)) < adiffmin) cycle
        if ((a(i,j+1) < a_over).and.(a(i,j) < a_over)) cycle
	diff=abs(a(i,j+1)-a(i,j))*frac
	amin=min(a(i,j+1),a(i,j))
	if (amin==0.) cycle
	!if (a(i,j+1)+a(i,j)-amin<aav*10.) cycle
	!write (*,*) diff,amin
	diff=amin*(1-exp(-diff/amin))
	if (a(i,j)<a(i,j+1)) then
		a(i,j)=a(i,j)-diff
		a(i,j+1)=a(i,j+1)+diff
	else
	a(i,j)=a(i,j)+diff
		a(i,j+1)=a(i,j+1)-diff
	end if
	end do
	end do	
	
		do i=1,nblock
	do j=1,nblock-1
	if (abs(a(j+1,i)-a(j,i)) < adiffmin) cycle
        if ((a(j+1,i) < a_over).and.(a(j,i) < a_over)) cycle
	diff=abs(a(j+1,i)-a(j,i))*frac
	amin=min(a(j+1,i),a(j,i))
	if (amin==0.) cycle
	!if (a(i,j+1)+a(i,j)-amin<aav*10.) cycle
	diff=amin*(1-exp(-diff/amin))
	if (a(j,i)<a(j+1,i)) then
		a(j,i)=a(j,i)-diff
		a(j+1,i)=a(j+1,i)+diff
	else
	a(j,i)=a(j,i)+diff
		a(j+1,i)=a(j+1,i)-diff
	end if
	end do
	end do	
	
	do i=1,nblock-1
	do j=1,nblock-1
	if (abs(a(j+1,i+1)-a(j,i)) < adiffmin) cycle
        if ((a(j+1,i+1) < a_over).and.(a(j,i) < a_over)) cycle
	diff=abs(a(j+1,i+1)-a(j,i))*frac
	amin=min(a(j+1,i+1),a(j,i))
	if (amin==0.) cycle
	!if (a(i,j+1)+a(i,j)-amin<aav*10.) cycle
	diff=amin*(1-exp(-diff/amin/sqrt(2.0)))
	if (a(j,i)<a(j+1,i+1)) then
		a(j,i)=a(j,i)-diff
		a(j+1,i+1)=a(j+1,i+1)+diff
	else
	a(j,i)=a(j,i)+diff
		a(j+1,i+1)=a(j+1,i+1)-diff
	end if
	end do
	end do	
	
	do i=2,nblock
	do j=1,nblock-1
	if (abs(a(j+1,i-1)-a(j,i)) < adiffmin) cycle
        if ((a(j+1,i-1) < a_over).and.(a(j,i) < a_over)) cycle
	diff=abs(a(j+1,i-1)-a(j,i))*frac
	amin=min(a(j+1,i-1),a(j,i))
	if (amin==0.) cycle
	!if (a(i,j+1)+a(i,j)-amin<aav*10.) cycle
	diff=amin*(1-exp(-diff/amin/sqrt(2.0)))
	if (a(j,i)<a(j+1,i-1)) then
		a(j,i)=a(j,i)-diff
		a(j+1,i-1)=a(j+1,i-1)+diff
	else
	a(j,i)=a(j,i)+diff
		a(j+1,i-1)=a(j+1,i-1)-diff
	end if
	end do
	end do	
	
	
	a=max(a,0.)
	
	do i=1,10
	write (*,'(10F8.3)') a(i,1:10)
	end do
	write (*,*) ''
		do i=1,nblock
	do j=1,nblock
	!if (j<680) vo2(int(a(i,j)),1+loop/10)=vo2(int(a(i,j)),1+loop/10)+1
	vo3(int(a(i,j)),1+loop/10)=vo3(int(a(i,j)),1+loop/10)+1
	end do
	end do
	last = 1+loop/10
	write (*,*) last
	end do
	
	
	
			do i=1,nblock
	do j=1,nblock-1
	write (3,*) i-1
	write (3,*) j-1
	write (3,*) a(i,j) !+sub !+aminn
	end do
	end do
	
	add=0.
	do j=0,10000
	if (mod(j,10)>0) add=add+vo2(j,6)
	if (mod(j,10)==0) then
	write (8,*) j,add
	add=0.
	end if
	write (7,*) j+aav,vo(j),vo2(j,last-1), vo3(j,last-1), vo3(j,last-1)/vo2(j,last-1)
	end do
	
	do i=1,nblock
	write (9,*) i,a(200,i), a(600,i)
	end do
	
	end
	
	
	
